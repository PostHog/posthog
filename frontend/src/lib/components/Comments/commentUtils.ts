import { generateText } from '@tiptap/core'

import { JSONContent } from 'lib/components/RichContentEditor/types'
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

    return generateText(content, DEFAULT_EXTENSIONS, serializationOptions)
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
