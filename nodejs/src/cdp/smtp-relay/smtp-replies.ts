export const SMTP_DOCS_URL = 'https://posthog.com/docs/workflows/smtp'

export class SmtpReply extends Error {
    constructor(
        public readonly responseCode: number,
        message: string
    ) {
        super(sanitizeReplyText(message))
    }

    public get isTemporary(): boolean {
        return this.responseCode < 500
    }

    /** The whole line as a client sees it. */
    public get line(): string {
        return `${this.responseCode} ${this.message}`
    }
}

// A reply is one line of ASCII, and Go's textproto rejects lines under four characters.
const MAX_REPLY_TEXT_LENGTH = 400

function sanitizeReplyText(text: string): string {
    const oneLine = text
        .replace(/[\r\n]+/g, ' ')
        .replace(/[^\x20-\x7E]/g, '?')
        .trim()
    return oneLine.length > MAX_REPLY_TEXT_LENGTH ? `${oneLine.slice(0, MAX_REPLY_TEXT_LENGTH - 3)}...` : oneLine
}

export const REPLIES = {
    tooManyConnections: () => new SmtpReply(421, '4.7.0 Too many connections from this address. Try again shortly.'),
    tooManyFailedLogins: () =>
        new SmtpReply(
            421,
            '4.7.0 Too many failed logins from this address. Check your key and try again in 5 minutes.'
        ),
    invalidCredentials: () =>
        new SmtpReply(535, `5.7.8 Invalid credentials. Use a project secret key as the password. ${SMTP_DOCS_URL}`),
    missingScope: () =>
        new SmtpReply(535, `5.7.8 This key needs the transactional_email:write scope. ${SMTP_DOCS_URL}`),
    notEnabled: () => new SmtpReply(535, '5.7.8 SMTP sending is not turned on for this project.'),
    authUnavailable: () => new SmtpReply(454, '4.7.0 Temporary authentication failure. Try again shortly.'),
    busy: () => new SmtpReply(451, '4.3.2 PostHog is busy. Retry shortly.'),
    tooLarge: (limitBytes: number) =>
        new SmtpReply(
            552,
            `5.3.4 Message too large. The limit is ${Math.floor(limitBytes / (1024 * 1024))} MB. Link to large files instead of attaching them.`
        ),
    unreadable: () => new SmtpReply(550, '5.6.0 PostHog could not read this message. Check that it is valid MIME.'),
    tooManyRecipients: (limit: number) =>
        new SmtpReply(554, `5.5.3 Too many recipients. The limit is ${limit} per message.`),
    signed: () =>
        new SmtpReply(554, '5.7.1 PostHog rewrites messages before sending, so S/MIME signed mail cannot be sent.'),
    noSender: () => new SmtpReply(550, '5.1.7 This message has no From header. Add one on a verified domain.'),
    severalSenders: () => new SmtpReply(550, '5.1.7 Use one address in the From header.'),
    unconfirmed: () =>
        new SmtpReply(
            451,
            "4.3.0 PostHog couldn't confirm this send, so it may still go out. Retry with the same idempotency key."
        ),
    someUnconfirmed: (queued: number, total: number) =>
        new SmtpReply(
            451,
            `4.3.0 PostHog queued ${queued} of ${total} recipients and couldn't confirm the rest. Retry to send to the rest.`
        ),
}

export type SendApiError = {
    status: number
    code?: string
    detail?: string
    attr?: string
}

export function replyForSendApiError({ status, code, detail, attr }: SendApiError): SmtpReply {
    if (status === 401 || status === 403) {
        return new SmtpReply(535, `5.7.8 This key can no longer send email. ${SMTP_DOCS_URL}`)
    }
    if (status === 404) {
        return new SmtpReply(550, '5.7.1 Sending email from code is not turned on for this project.')
    }
    if (status === 409) {
        return new SmtpReply(451, '4.3.0 An earlier send with this key is still processing. Retry shortly.')
    }
    if (status === 413) {
        return new SmtpReply(552, `5.3.4 This email is larger than PostHog can send. ${SMTP_DOCS_URL}`)
    }
    if (status === 429) {
        return code === 'quota_limited'
            ? new SmtpReply(451, '4.7.1 This project is over its email quota. Check your billing settings.')
            : new SmtpReply(451, '4.7.1 Rate limit reached. Retry shortly.')
    }
    switch (code) {
        case 'recipient_suppressed':
            return new SmtpReply(
                550,
                '5.7.1 A recipient is suppressed after a hard bounce or complaint. Remove it from the suppression list if it is valid.'
            )
        case 'recipient_unreachable':
            return new SmtpReply(550, '5.1.2 A recipient cannot receive email. Check for a typo.')
        case 'sending_suspended':
        case 'sending_paused':
            return new SmtpReply(554, '5.7.1 Sending is suspended or paused for this project. See the Reputation tab.')
        case 'idempotency_key_reused':
            return new SmtpReply(554, '5.7.0 This idempotency key was used for a different email. Use a new key.')
        case 'sender_not_verified':
        case 'sender_required':
        case 'sender_unavailable':
            return new SmtpReply(550, `5.7.1 ${detail ?? 'The From address is not a verified sender on this project.'}`)
    }
    if (status === 400) {
        const field = attr?.split('__')[0]
        if (field === 'to' || field === 'cc' || field === 'bcc') {
            return new SmtpReply(
                553,
                "5.1.3 PostHog can't send to this address. Quoted names, IP addresses and non-ASCII domains aren't supported."
            )
        }
        if (field === 'from') {
            return new SmtpReply(550, `5.1.7 The From header is not valid. ${detail ?? ''}`)
        }
        if (field === 'attachments' && detail?.includes('MB')) {
            return new SmtpReply(552, `5.3.4 ${detail} Link to large files instead of attaching them.`)
        }
        if (field === 'attachments') {
            return new SmtpReply(554, `5.7.1 ${detail ?? 'PostHog cannot send one of the attachments.'}`)
        }
        return new SmtpReply(550, `5.6.0 ${detail ?? 'PostHog could not accept this message.'}`)
    }
    return REPLIES.unconfirmed()
}
