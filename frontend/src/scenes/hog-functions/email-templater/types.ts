import { Editor } from 'react-email-editor'

import type { ReactEmailDesign } from './react-email/types'

type UnlayerJSONTemplate = Parameters<Editor['loadDesign']>[0]

/**
 * Designs produced by the Unlayer editor have a `body`/`counters`/`schemaVersion`
 * shape; designs produced by `@react-email/editor` are TipTap JSONContent with
 * `type: 'doc'`. Both can live in the same `design` field — the logic picks
 * which editor to use based on the shape.
 */
export type EmailDesign = UnlayerJSONTemplate | ReactEmailDesign

export type EmailTemplate = {
    design: EmailDesign | null
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
