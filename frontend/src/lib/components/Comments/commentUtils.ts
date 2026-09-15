import { generateText } from '@tiptap/core'

import { JSONContent, RichContentNodeType } from 'lib/components/RichContentEditor/types'
import { dayjs } from 'lib/dayjs'
import { DEFAULT_EXTENSIONS, serializationOptions } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'
import { urls } from 'scenes/urls'

import { ActivityScope } from '~/types'

export interface RecordingLinkInfo {
    recordingId: string
    unixTimestampMillis: number | undefined
    url: string
}

export type RecordingCommentTarget = {
    scope: ActivityScope | string
    item_id?: string | null
    item_context?: { time_in_recording?: string | null } | null
}

export function getRecordingLinkInfo(comment: RecordingCommentTarget): RecordingLinkInfo | null {
    const isRecordingComment = comment.scope === ActivityScope.REPLAY || comment.scope === ActivityScope.RECORDING
    if (!isRecordingComment || !comment.item_id) {
        return null
    }
    const timeInRecording = comment.item_context?.time_in_recording
    const unixTimestampMillis = timeInRecording ? dayjs(timeInRecording).valueOf() : undefined
    const url = urls.replaySingle(comment.item_id, unixTimestampMillis ? { unixTimestampMillis } : undefined)
    return {
        recordingId: comment.item_id,
        unixTimestampMillis,
        url,
    }
}

export function getCommentText(comment: { content?: string | null; rich_content?: JSONContent | null }): string {
    // This is only temporary until all comments are backfilled to rich content
    const content = comment.rich_content
        ? comment.rich_content
        : {
              type: 'doc',
              content: [
                  {
                      type: 'paragraph',
                      content: comment.content
                          ? [
                                {
                                    type: 'text',
                                    text: comment.content,
                                },
                            ]
                          : [],
                  },
              ],
          }

    try {
        return generateText(content, DEFAULT_EXTENSIONS, serializationOptions)
    } catch {
        // generateText builds a schema from DEFAULT_EXTENSIONS, which keeps no marks (italic, bold,
        // link, ...) and only paragraph/mention nodes. Conversations authors comments with a richer
        // schema, so any such mark or node makes ProseMirror throw "There is no mark type ... in this
        // schema". Fall back to a schema-free walk so one formatted comment can't crash the caller.
        return extractPlainText(content)
    }
}

/** Inline node types that concatenate with no separator, as opposed to block nodes separated by a blank line. */
const INLINE_NODE_TYPES = new Set<string>(['text', 'hardBreak', RichContentNodeType.Mention])

/**
 * Concatenate the text of a rich-content doc without a ProseMirror schema, so no node or mark can throw.
 * Block children are separated by a blank line to match generateText's default block separator, while
 * inline runs within a block concatenate directly.
 */
function extractPlainText(node: JSONContent): string {
    if (node.type === RichContentNodeType.Mention) {
        return `@member:${node.attrs?.id}`
    }
    if (node.type === 'hardBreak') {
        return '\n'
    }
    const children = node.content ?? []
    const joined = children
        .map(extractPlainText)
        .map((part, index) => {
            const isBlock = index > 0 && !INLINE_NODE_TYPES.has(children[index].type ?? '')
            return isBlock ? `\n\n${part}` : part
        })
        .join('')
    return (node.text ?? '') + joined
}

export function isViewingRecording(recordingId: string): boolean {
    const url = new URL(window.location.href)
    const pathMatch = url.pathname.match(/\/replay\/([^/?#]+)/)
    if (pathMatch && pathMatch[1] === recordingId) {
        return true
    }
    const sessionRecordingId =
        url.searchParams.get('sessionRecordingId') || url.hash.match(/sessionRecordingId=([^&]+)/)?.[1]
    return sessionRecordingId === recordingId
}
