import { Editor } from 'react-email-editor'

type JSONTemplate = Parameters<Editor['loadDesign']>[0]

export const MAX_WORKFLOW_EMAIL_SENDERS = 10

// Native email senders: integrationIds enables stable per-run rotation, while the optional
// templated overrides vary the visible sender. The runtime rejects an override address that
// is not on the selected integration's verified domain.
export type EmailTemplateFrom = {
    integrationId?: number
    integrationIds?: number[]
    email?: string
    name?: string
}

export type EmailTemplate = {
    design: JSONTemplate | null
    html: string
    subject: string
    text: string
    // A bare template string for legacy `email` inputs; an EmailTemplateFrom for `native_email`.
    from: string | EmailTemplateFrom
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
