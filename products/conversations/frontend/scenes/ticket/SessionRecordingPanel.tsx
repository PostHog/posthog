import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { urls } from 'scenes/urls'

import { PersonsTabType } from '~/types'

interface SessionRecordingPanelProps {
    sessionContext?: {
        replay_url?: unknown
        [key: string]: any
    }
    distinctId?: string
}

/** The widget stores the replay URL under `replay_url`. The id is its last path segment. */
export function recordingIdFromReplayUrl(replayUrl: unknown): string | null {
    if (typeof replayUrl !== 'string' || !replayUrl) {
        return null
    }
    return replayUrl.split('?')[0].split('/').filter(Boolean).pop() ?? null
}

export function SessionRecordingPanel({ sessionContext, distinctId }: SessionRecordingPanelProps): JSX.Element {
    const recordingId = recordingIdFromReplayUrl(sessionContext?.replay_url)

    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'session-recording',
                    header: 'Session recording',
                    content: (
                        <div>
                            {!recordingId ? (
                                <div className="text-muted-alt text-xs">No session recording available</div>
                            ) : (
                                <div className="max-h-[500px] h-[500px] flex justify-center items-center">
                                    <SessionRecordingPlayer
                                        sessionRecordingId={recordingId}
                                        playerKey={`ticket-recording-${recordingId}`}
                                        autoPlay={false}
                                    />
                                </div>
                            )}
                            {distinctId && (
                                <div className="mt-2 pt-2 border-t flex justify-end">
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        to={`${urls.personByDistinctId(distinctId)}#activeTab=${PersonsTabType.SESSION_RECORDINGS}`}
                                    >
                                        See all recordings →
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
