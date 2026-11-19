import { EmailMetaFieldKey } from './emailTemplaterLogic'

export type OptionalHeaderField = {
    key: Extract<EmailMetaFieldKey, 'cc' | 'bcc' | 'preheader'>
    label: string
    info: string
}

export const COPY_HEADER_FIELDS: OptionalHeaderField[] = [
    { key: 'cc', label: 'Cc', info: 'Comma-separated list of CC recipients.' },
    { key: 'bcc', label: 'Bcc', info: 'Comma-separated list of BCC recipients.' },
]

export const PREHEADER_FIELD: OptionalHeaderField = {
    key: 'preheader',
    label: 'Preheader',
    info: 'This is the preview text that appears below the subject line in an inbox.',
}

export function isHeaderFieldShown(visibleFields: { key: string }[], key: string): boolean {
    return visibleFields.some((field) => field.key === key)
}
