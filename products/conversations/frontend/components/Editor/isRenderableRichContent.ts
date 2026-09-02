import { JSONContent, getSchema } from '@tiptap/core'
import { Node as ProseMirrorNode } from '@tiptap/pm/model'

import { SUPPORT_PREVIEW_EXTENSIONS } from './SupportEditor'

let previewSchema: ReturnType<typeof getSchema> | null = null

/**
 * Whether stored rich content can be rendered against the preview schema.
 *
 * The request serializers accept any JSON-serializable shape, so a message can carry known node
 * types in a structure the schema rejects. Everything that consumes a message's rich content has
 * to agree on this verdict, otherwise a reader sees the plain-text fallback while another surface
 * shows something else.
 */
export function isRenderableRichContent(content: JSONContent | null | undefined): content is JSONContent {
    if (!content) {
        return false
    }
    try {
        previewSchema = previewSchema ?? getSchema([...SUPPORT_PREVIEW_EXTENSIONS])
        ProseMirrorNode.fromJSON(previewSchema, content).check()
        return true
    } catch {
        return false
    }
}
