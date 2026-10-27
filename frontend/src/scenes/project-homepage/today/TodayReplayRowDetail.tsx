import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { Button, Skeleton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import 'scenes/session-recordings/playlist/SessionRecordingPreview.scss'
import { SessionRecordingPreview } from 'scenes/session-recordings/playlist/SessionRecordingPreview'

import { todayReplayPreviewLogic } from './todayReplayPreviewLogic'

export function TodayReplayRowDetail({
    savedFilterId,
    to,
    onOpen,
}: {
    savedFilterId: string
    to: string
    onOpen: () => void
}): JSX.Element {
    const logic = todayReplayPreviewLogic({ savedFilterId })
    const { preview, previewLoading, previewFailed, activeRecording, selectedRecordingId } = useValues(logic)
    const { loadPreview, selectRecording } = useActions(logic)

    const body = previewLoading ? (
        <div className="TodayReplay__body" aria-busy aria-label="Loading recordings">
            <Skeleton className="TodayReplay__player" />
            <div className="flex flex-col gap-2">
                {['w-4/5', 'w-3/5', 'w-2/3'].map((width) => (
                    <Skeleton key={width} className={`h-10 ${width}`} />
                ))}
            </div>
        </div>
    ) : previewFailed ? (
        <div className="TodayHome__note flex flex-wrap items-center gap-x-2">
            <span>These recordings didn't load.</span>
            <Button variant="outline" size="sm" onClick={() => loadPreview()} data-attr="today-replay-preview-retry">
                Try again
            </Button>
        </div>
    ) : !preview || preview.recordings.length === 0 ? (
        <p className="TodayHome__note">No recordings match this saved filter right now.</p>
    ) : (
        <div className="TodayReplay__body">
            <div className="TodayReplay__player">
                {activeRecording && (
                    <SessionRecordingPlayer
                        sessionRecordingId={activeRecording.id}
                        playerKey={`today-replay-${savedFilterId}`}
                        autoPlay={!!selectedRecordingId}
                        noMeta
                        noBorder
                        withSidebar={false}
                    />
                )}
            </div>
            <ol className="TodayReplay__list" aria-label="Recordings">
                {preview.recordings.map((recording) => (
                    <li key={recording.id}>
                        <button
                            type="button"
                            className="TodayReplay__recording"
                            aria-current={recording.id === activeRecording?.id || undefined}
                            onClick={() => selectRecording(recording.id)}
                            data-attr="today-replay-preview-recording"
                        >
                            <SessionRecordingPreview
                                recording={recording}
                                isActive={recording.id === activeRecording?.id}
                                order="start_time"
                            />
                        </button>
                    </li>
                ))}
            </ol>
        </div>
    )

    return (
        <div className="TodayRow__detailBody">
            {body}
            <div className="TodayRow__detailFooter">
                <p className="TodayRow__detailFacts">
                    {preview && preview.recordings.length > 0 && (
                        <span>
                            {preview.hasMore
                                ? `Latest ${preview.recordings.length} recordings`
                                : `${preview.recordings.length} ${preview.recordings.length === 1 ? 'recording' : 'recordings'}`}
                        </span>
                    )}
                </p>
                <div className="TodayRow__detailActions">
                    <Button
                        variant="outline"
                        size="sm"
                        nativeButton={false}
                        render={<LinkPrimitive to={to} />}
                        onClick={onOpen}
                        data-attr="today-replay-preview-open"
                    >
                        Go to session replay
                        <IconArrowRight />
                    </Button>
                </div>
            </div>
        </div>
    )
}
