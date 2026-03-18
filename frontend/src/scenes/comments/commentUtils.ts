import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { ActivityScope, CommentType } from '~/types'

export interface RecordingLinkInfo {
    recordingId: string
    unixTimestampMillis: number | undefined
    url: string
}

export function getRecordingLinkInfo(comment: CommentType): RecordingLinkInfo | null {
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
