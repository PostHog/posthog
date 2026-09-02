import { useActions } from 'kea'

import { IconExpand45, IconExternal } from '@posthog/icons'
import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { PersonsTabType } from '~/types'

import { RecordingSummary } from 'products/replay_vision/frontend/components/RecordingSummary'

interface SessionRecordingPanelProps {
    sessionContext?: {
        session_replay_url?: string
        [key: string]: any
    }
    distinctId?: string
}

// The widget stores the replay link as a path like /replay/:recordingId, sometimes with a query string.
function recordingIdFromReplayUrl(replayUrl: string | undefined): string | null {
    if (!replayUrl) {
        return null
    }
    return replayUrl.split('?')[0].split('/').filter(Boolean).pop() ?? null
}

export function SessionRecordingPanel({ sessionContext, distinctId }: SessionRecordingPanelProps): JSX.Element {
    const recordingId = recordingIdFromReplayUrl(sessionContext?.session_replay_url)
    const playerKey = `ticket-recording-${recordingId}`
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)

    const inlinePlayer = (): ReturnType<typeof sessionRecordingPlayerLogic.findMounted> =>
        recordingId ? sessionRecordingPlayerLogic.findMounted({ sessionRecordingId: recordingId, playerKey }) : null

    const expandRecording = (): void => {
        if (!recordingId) {
            return
        }
        // The modal is a second player for the same recording, so this one must not keep playing behind it
        inlinePlayer()?.actions.setPause()
        openSessionPlayer({ id: recordingId })
    }

    const seeAllRecordings = distinctId ? (
        <LemonButton
            type="tertiary"
            size="xsmall"
            className="ml-auto"
            to={`${urls.personByDistinctId(distinctId)}#activeTab=${PersonsTabType.SESSION_RECORDINGS}`}
            data-attr="ticket-recording-see-all"
        >
            See all recordings →
        </LemonButton>
    ) : null

    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'session-recording',
                    header: 'Session recording',
                    content: recordingId ? (
                        <div className="flex flex-col">
                            {/* Cancels the collapse body padding so the player gets the full column width. Height follows that width, so a narrow column does not get a tall box around a tiny frame. */}
                            <div className="flex -mx-4 -mt-4 border-b aspect-[16/11] min-h-60 max-h-[26rem]">
                                <SessionRecordingPlayer
                                    sessionRecordingId={recordingId}
                                    playerKey={playerKey}
                                    mode={SessionRecordingPlayerMode.Standard}
                                    autoPlay={false}
                                    noMeta
                                    noBorder
                                    noDock
                                    withSidebar={false}
                                />
                            </div>
                            <div className="py-3 border-b">
                                <RecordingSummary
                                    sessionId={recordingId}
                                    onSeek={(timestampMs) => inlinePlayer()?.actions.seekToTime(timestampMs)}
                                />
                            </div>
                            <div className="flex flex-wrap items-center justify-between gap-2 pt-3">
                                <div className="flex flex-wrap gap-1">
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        icon={<IconExpand45 />}
                                        onClick={expandRecording}
                                        tooltip="Watch in a larger view with the activity panel"
                                        data-attr="ticket-recording-expand"
                                    >
                                        Expand
                                    </LemonButton>
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        icon={<IconExternal />}
                                        to={urls.replaySingle(recordingId)}
                                        targetBlank
                                        data-attr="ticket-recording-open-replay"
                                    >
                                        Open in replay
                                    </LemonButton>
                                </div>
                                {seeAllRecordings}
                            </div>
                        </div>
                    ) : (
                        <div>
                            <div className="text-muted-alt text-xs">No recording was captured for this session.</div>
                            {seeAllRecordings && (
                                <div className="mt-2 pt-2 border-t flex justify-end">{seeAllRecordings}</div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
