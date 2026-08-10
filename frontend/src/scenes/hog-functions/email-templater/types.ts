import { Editor } from 'react-email-editor'

type JSONTemplate = Parameters<Editor['loadDesign']>[0]

export type EmailTemplate = {
    design: JSONTemplate | null
    html: string
    subject: string
    text: string
    from: string
    to: string
    replyTo?: string
    cc?: string
    bcc?: string
    preheader?: string
}

// Per-field validation messages surfaced next to the sender, recipient, subject, and body
// inputs. Callers that validate an email step (e.g. the workflow builder) pass these in so the
// templater can place each message on its field instead of joining them into one blob.
export type EmailFieldErrors = {
    from?: string
    to?: string
    subject?: string
    body?: string
}
