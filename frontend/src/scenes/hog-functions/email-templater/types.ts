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
