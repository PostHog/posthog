import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { RichContentPreview } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { colonDelimitedDuration } from 'lib/utils/durations'

import { CommentType } from '~/types'

import { sessionRecordingCommentsLogic } from '../sessionRecordingCommentsLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export function RecordingCommentsList({ sessionId }: { sessionId: string }): JSX.Element | null {
    const { sessionComments, sessionCommentsLoading } = useValues(
        sessionRecordingCommentsLogic({ sessionRecordingId: sessionId })
    )
    const { logicProps, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)

    const startMs = sessionPlayerData.start?.valueOf() ?? null
    const timeInRecordingMs = (comment: CommentType): number | null => {
        const at = comment.item_context?.time_in_recording
        return at && startMs !== null ? dayjs(at).valueOf() - startMs : null
    }
    const seek = (ms: number): void => {
        sessionRecordingPlayerLogic.findMounted(logicProps)?.actions.seekToTime(ms)
    }
    const comments = [...sessionComments].sort(
        (a, b) => (timeInRecordingMs(a) ?? Infinity) - (timeInRecordingMs(b) ?? Infinity)
    )
    if (comments.length === 0 && !sessionCommentsLoading) {
        return null
    }

    return (
        <div className="flex flex-col gap-2" data-attr="watch-panel-comments">
            {sessionCommentsLoading && comments.length === 0 ? (
                <LemonSkeleton className="w-2/3 h-4" />
            ) : (
                comments.map((comment) => {
                    const atMs = timeInRecordingMs(comment)
                    return (
                        <div key={comment.id} className="flex items-start gap-2 text-sm">
                            <ProfilePicture user={comment.created_by} size="sm" className="mt-0.5" />
                            <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                                <div className="flex items-center gap-2 text-xs text-secondary">
                                    <span className="font-medium text-primary">
                                        {comment.created_by?.first_name || comment.created_by?.email || 'Someone'}
                                    </span>
                                    <TZLabel time={comment.created_at} showPopover={false} />
                                    {atMs !== null && (
                                        <LemonButton
                                            size="xsmall"
                                            onClick={() => seek(atMs)}
                                            data-attr="watch-panel-comment-seek"
                                        >
                                            <span className="tabular-nums">
                                                {colonDelimitedDuration(atMs / 1000, 2)}
                                            </span>
                                        </LemonButton>
                                    )}
                                </div>
                                {comment.rich_content ? (
                                    <RichContentPreview content={comment.rich_content} className="rounded-none" />
                                ) : (
                                    <TextContent text={comment.content ?? ''} />
                                )}
                            </div>
                        </div>
                    )
                })
            )}
        </div>
    )
}
