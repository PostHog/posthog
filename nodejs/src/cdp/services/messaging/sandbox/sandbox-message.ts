import { z } from 'zod'

import { sanitizeEmailSubject } from '../email.service'
import { escapeHtml } from '../helpers/escape-html'
import { maybeAddPreheaderToEmail } from '../helpers/preheader'

export const SandboxRenderedEmailSchema = z
    .object({
        to: z.object({ email: z.string().min(1), name: z.string().optional() }),
        subject: z.string().min(1),
        preheader: z.string().optional(),
        text: z.string().optional(),
        html: z.string().optional(),
    })
    .refine((email) => !!email.text || !!email.html)

export type SandboxRenderedEmail = z.infer<typeof SandboxRenderedEmailSchema>

export type SandboxMessage = {
    from: { address: string; name: string }
    to: { address: string; name?: string }
    subject: string
    text?: string
    html?: string
    headers: { name: string; value: string }[]
}

const BODY_CLOSE_TAG = /<\/body\s*>/gi
const CONTROL_CHARACTERS = /[\x00-\x1F\x7F]/g

export function buildSandboxMessage({
    email,
    organizationId,
    organizationName,
    fromAddress,
    recipient,
}: {
    email: SandboxRenderedEmail
    organizationId: string
    organizationName: string
    fromAddress: string
    recipient: string
}): SandboxMessage {
    const senderName = `${cleanDisplayName(organizationName)} via PostHog`
    const recipientName = cleanDisplayName(email.to.name ?? '')
    const footer = `This email was sent by ${senderName} with the PostHog sandbox sender. Organization ID: ${organizationId}.`
    return {
        from: { address: fromAddress, name: senderName },
        to: { address: recipient, ...(recipientName ? { name: recipientName } : {}) },
        subject: sanitizeEmailSubject(email.subject),
        ...(email.text ? { text: `${email.text}\n\n${footer}` } : {}),
        ...(email.html
            ? { html: appendHtmlFooter(maybeAddPreheaderToEmail(email.html, email.preheader), footer) }
            : {}),
        headers: [{ name: 'X-PostHog-Organization-Id', value: organizationId }],
    }
}

function cleanDisplayName(name: string): string {
    return name.replace(CONTROL_CHARACTERS, '').trim()
}

function appendHtmlFooter(html: string, footer: string): string {
    const footerHtml = `<div>${escapeHtml(footer)}</div>`
    const bodyClose = [...html.matchAll(BODY_CLOSE_TAG)].at(-1)
    if (!bodyClose) {
        return html + footerHtml
    }
    return html.slice(0, bodyClose.index) + footerHtml + html.slice(bodyClose.index)
}
