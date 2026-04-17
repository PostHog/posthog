import { JSONContent } from '@tiptap/core'

export type EmailTemplate = {
    design: JSONContent | null
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
