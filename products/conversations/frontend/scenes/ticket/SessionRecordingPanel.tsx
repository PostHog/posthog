import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { urls } from 'scenes/urls'

import { PersonsTabType } from '~/types'

interface SessionRecordingPanelProps {
    sessionContext?: {
        session_replay_url?: string
        [key: string]: any
    }
    distinctId?: string
}

export function SessionRecordingPanel({ sessionContext, distinctId }: SessionRecordingPanelProps): JSX.Element {
    // Extract recording ID from session_replay_url
    // URL format: /replay/:recordingId or similar
    const recordingId = sessionContext?.session_replay_url
        ? sessionContext.session_replay_url.split('/').pop()?.split('?')[0]
        : null

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
                                <div style={{ minHeight: '400px' }}>
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
