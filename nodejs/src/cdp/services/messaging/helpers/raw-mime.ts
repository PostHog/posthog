import { MessageHeader } from '@aws-sdk/client-sesv2'
import MailComposer from 'nodemailer/lib/mail-composer'
import Mail from 'nodemailer/lib/mailer'

import { EmailAttachment } from '~/cdp/schema/emailFields'

export type RawEmail = {
    from: string
    to: string
    cc?: string[]
    replyTo?: string[]
    subject: string
    text?: string
    html?: string
    headers: MessageHeader[]
    attachments: EmailAttachment[]
}

export function composeRawEmail(email: RawEmail): Promise<Buffer> {
    return new MailComposer(toMailOptions(email)).compile().build()
}

export function toMailAttachment({ filename, content, contentType, contentId }: EmailAttachment): Mail.Attachment {
    return { filename, content: Buffer.from(content, 'base64'), contentType, cid: contentId }
}

function toMailOptions(email: RawEmail): Mail.Options {
    return {
        from: email.from,
        to: email.to,
        cc: email.cc,
        replyTo: email.replyTo,
        subject: email.subject,
        text: email.text,
        html: email.html,
        headers: preparedHeaders(email.headers),
        attachments: email.attachments.map(toMailAttachment),
        // Attachments arrive from API callers, so a `path` or `href` must never make the worker read a file or fetch a URL.
        disableFileAccess: true,
        disableUrlAccess: true,
    }
}

// Values arrive checked as one line of printable ASCII. Sent unfolded, the tracking code reaches the delivery
// webhook exactly as signed. A list, because nodemailer reads an object with `key` and `value` names as one
// header; its types leave out the prepared value that the list takes as well.
function preparedHeaders(headers: MessageHeader[]): Mail.Headers {
    const prepared = headers.map(({ Name, Value }) => ({
        key: Name ?? '',
        value: { prepared: true, value: Value ?? '' },
    }))
    return prepared as unknown as Mail.Headers
}
