import { createHash } from 'crypto'
import { AddressObject, ParsedMail, simpleParser } from 'mailparser'

import { REPLIES } from './smtp-replies'

export const SMTP_TEMPLATE_KEY = 'smtp'
export const MAX_TO_RECIPIENTS = 50
export const MAX_COPY_RECIPIENTS = 10
export const MAX_FORWARDED_HEADERS = 10

const TEMPLATE_KEY_RE = /^[a-zA-Z0-9_-]{1,400}$/
const FORWARDED_HEADERS = new Set(['in-reply-to', 'references', 'list-unsubscribe', 'list-unsubscribe-post', 'list-id'])
// Used up by the relay, or describing the message the relay takes apart. None of these is dropped from the caller's
// point of view, so none is reported as dropped.
const CONSUMED_HEADERS = new Set([
    'bcc',
    'cc',
    'content-disposition',
    'content-id',
    'content-transfer-encoding',
    'content-type',
    'date',
    'dkim-signature',
    'from',
    'message-id',
    'mime-version',
    'posthog-idempotency-key',
    'received',
    'reply-to',
    'resend-idempotency-key',
    'return-path',
    'subject',
    'to',
    'user-agent',
    'x-mailer',
    'x-posthog-capture-engagement',
    'x-posthog-distinct-id',
    'x-posthog-template-key',
])
const RESERVED_HEADER_RE = /^x-(posthog|ses)-/

export type SmtpAttachment = {
    filename: string
    content: string
    content_type?: string
    content_id?: string
}

export type SmtpSend = {
    idempotencyKey?: string
    body: {
        to: string
        cc?: string[]
        bcc?: string[]
        template_key: string
        subject: string
        html?: string
        text?: string
        from: string
        reply_to?: string[]
        attachments?: SmtpAttachment[]
        headers?: Record<string, string>
        capture_engagement: boolean
        track_opens_and_clicks: boolean
        distinct_id?: string
    }
}

export type SmtpPlan = {
    sends: SmtpSend[]
    fromAddress: string
    droppedHeaders: string[]
}

export async function parseSmtpMessage(raw: Buffer): Promise<ParsedMail> {
    try {
        // Keeps `cid:` links, which the parser otherwise turns into data URIs, and adds no derived bodies.
        return await simpleParser(raw, {
            keepCidLinks: true,
            skipHtmlToText: true,
            skipTextToHtml: true,
            skipTextLinks: true,
            skipImageLinks: true,
        })
    } catch {
        throw REPLIES.unreadable()
    }
}

const addressesIn = (field: AddressObject | AddressObject[] | undefined): { name: string; address: string }[] => {
    const groups = Array.isArray(field) ? field : field ? [field] : []
    const entries = groups.flatMap((group) => group.value)
    return entries.flatMap((entry) =>
        entry.group
            ? entry.group.flatMap((member) => (member.address ? [{ name: member.name, address: member.address }] : []))
            : entry.address
              ? [{ name: entry.name, address: entry.address }]
              : []
    )
}

const normalize = (address: string): string => address.trim().toLowerCase()

function rawHeaderValue(parsed: ParsedMail, name: string): string | undefined {
    const line = parsed.headerLines.find((header) => header.key === name)?.line
    if (line === undefined) {
        return undefined
    }
    return line
        .slice(line.indexOf(':') + 1)
        .replace(/\r?\n[ \t]+/g, ' ')
        .trim()
}

function forwardedHeaders(parsed: ParsedMail): { headers: Record<string, string>; dropped: string[] } {
    const headers: Record<string, string> = {}
    const dropped: string[] = []
    const seen = new Set<string>()
    for (const { key, line } of parsed.headerLines) {
        if (seen.has(key) || CONSUMED_HEADERS.has(key)) {
            continue
        }
        seen.add(key)
        const name = line.slice(0, line.indexOf(':')).trim()
        const value = rawHeaderValue(parsed, key)
        const forwardable =
            !RESERVED_HEADER_RE.test(key) && (FORWARDED_HEADERS.has(key) || key.startsWith('x-')) && !!value
        if (forwardable && Object.keys(headers).length < MAX_FORWARDED_HEADERS && value.length <= 998) {
            headers[name] = value
        } else {
            dropped.push(name)
        }
    }
    return { headers, dropped }
}

function attachmentsOf(parsed: ParsedMail): SmtpAttachment[] {
    return parsed.attachments.map((attachment, index) => {
        // A file name with a path, or none at all, is refused by the send API.
        const baseName = (attachment.filename ?? '').split(/[\\/]/).pop()?.trim()
        const contentId = attachment.related ? attachment.cid?.replace(/[<>]/g, '') : undefined
        const contentType = attachment.contentType?.split(';')[0].trim()
        return {
            filename: baseName || `attachment-${index + 1}`,
            content: attachment.content.toString('base64'),
            ...(contentType && { content_type: contentType }),
            ...(contentId && { content_id: contentId }),
        }
    })
}

function displayName(name: string, address: string): string {
    return name ? `"${name.replace(/[\\"]/g, '\\$&')}" <${address}>` : address
}

function senderOf(parsed: ParsedMail, envelopeFrom: string | undefined): { from: string; address: string } {
    const senders = addressesIn(parsed.from)
    if (senders.length > 1) {
        throw REPLIES.severalSenders()
    }
    const sender = senders[0] ?? (envelopeFrom ? { name: '', address: envelopeFrom } : undefined)
    if (!sender) {
        throw REPLIES.noSender()
    }
    return { from: displayName(sender.name, sender.address), address: sender.address }
}

// The envelope decides who gets the email. The headers only decide who sees whom.
function recipientsOf(
    parsed: ParsedMail,
    envelopeTo: string[]
): {
    to: string[]
    cc: string[]
    bcc: string[]
} {
    const inTo = new Set(addressesIn(parsed.to).map(({ address }) => normalize(address)))
    const inCc = new Set(addressesIn(parsed.cc).map(({ address }) => normalize(address)))
    const unique = [...new Map(envelopeTo.map((address) => [normalize(address), address.trim()])).values()]
    const to = unique.filter((address) => inTo.has(normalize(address)))
    const cc = unique.filter((address) => !inTo.has(normalize(address)) && inCc.has(normalize(address)))
    const bcc = unique.filter((address) => !inTo.has(normalize(address)) && !inCc.has(normalize(address)))
    if (to.length === 0) {
        const promoted = cc.shift() ?? bcc.shift()
        if (promoted) {
            to.push(promoted)
        }
    }
    return { to, cc, bcc }
}

function idempotencyBase(parsed: ParsedMail): string | undefined {
    const explicit =
        rawHeaderValue(parsed, 'posthog-idempotency-key') ?? rawHeaderValue(parsed, 'resend-idempotency-key')
    if (explicit) {
        return `key:${explicit}`
    }
    return parsed.messageId ? `message-id:${parsed.messageId}` : undefined
}

const perRecipientKey = (base: string | undefined, to: string): string | undefined =>
    base
        ? `smtp-${createHash('sha256')
              .update(`${base}\n${normalize(to)}`)
              .digest('hex')}`
        : undefined

function isSigned(parsed: ParsedMail): boolean {
    const contentType = parsed.headers.get('content-type') as { value?: string } | undefined
    return contentType?.value === 'multipart/signed' || contentType?.value === 'application/pkcs7-mime'
}

/** Turns one SMTP message into the send API requests that deliver it. Throws an SmtpReply when it can't be sent. */
export function planSends(parsed: ParsedMail, envelope: { from?: string; to: string[] }): SmtpPlan {
    if (isSigned(parsed)) {
        throw REPLIES.signed()
    }
    const { to, cc, bcc } = recipientsOf(parsed, envelope.to)
    if (to.length > MAX_TO_RECIPIENTS) {
        throw REPLIES.tooManyRecipients(MAX_TO_RECIPIENTS)
    }
    if (cc.length > MAX_COPY_RECIPIENTS || bcc.length > MAX_COPY_RECIPIENTS) {
        throw REPLIES.tooManyRecipients(MAX_COPY_RECIPIENTS)
    }
    const sender = senderOf(parsed, envelope.from)
    const { headers, dropped } = forwardedHeaders(parsed)
    const replyTo = addressesIn(parsed.replyTo).map(({ address }) => address)
    const attachments = attachmentsOf(parsed)
    const templateKey = rawHeaderValue(parsed, 'x-posthog-template-key')
    const distinctId = rawHeaderValue(parsed, 'x-posthog-distinct-id')
    const base = idempotencyBase(parsed)
    const html = typeof parsed.html === 'string' ? parsed.html : ''
    // Mail tools can send a subject or a body alone, and the send API needs both.
    const text = parsed.text || (html ? '' : ' ')

    // Tracking stays off unless asked for: this mail often carries single-use links, which a rewrite can break.
    const tracked = rawHeaderValue(parsed, 'x-posthog-capture-engagement')?.toLowerCase() === 'true'
    const shared = {
        template_key: templateKey && TEMPLATE_KEY_RE.test(templateKey) ? templateKey : SMTP_TEMPLATE_KEY,
        subject: parsed.subject || '(no subject)',
        from: sender.from,
        capture_engagement: tracked,
        track_opens_and_clicks: tracked,
        ...(html && { html }),
        ...(text && { text }),
        ...(replyTo.length > 0 && { reply_to: replyTo }),
        ...(attachments.length > 0 && { attachments }),
        ...(Object.keys(headers).length > 0 && { headers }),
        ...(distinctId && { distinct_id: distinctId }),
    }
    return {
        fromAddress: sender.address,
        droppedHeaders: dropped,
        sends: to.map((address, index) => ({
            idempotencyKey: perRecipientKey(base, address),
            body: {
                ...shared,
                to: address,
                // Copies go out once, with the first send.
                ...(index === 0 && cc.length > 0 && { cc }),
                ...(index === 0 && bcc.length > 0 && { bcc }),
            },
        })),
    }
}
