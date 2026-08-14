import { useValues } from 'kea'
import { useState } from 'react'

import { PostHogErrorBoundary } from '@posthog/react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { teamLogic } from 'scenes/teamLogic'

export interface PlayerFrameErrorBoundaryProps {
    sessionRecordingId: string
    children: React.ReactNode
}

// Contains rrweb replayer render faults to the frame, so the timeline, inspector, and playlist
// keep working and the viewer can retry or open another recording without reloading the scene.
export function PlayerFrameErrorBoundary({ sessionRecordingId, children }: PlayerFrameErrorBoundaryProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [retryKey, setRetryKey] = useState(0)

    const additionalProperties: Record<string, string | number> = {
        feature: 'replay-player',
        session_recording_id: sessionRecordingId,
    }
    if (currentTeamId != null) {
        additionalProperties.team_id = currentTeamId
    }

    return (
        <PostHogErrorBoundary
            // A new key discards the caught error and remounts the frame when the viewer retries.
            key={retryKey}
            additionalProperties={additionalProperties}
            fallback={
                <div className="flex flex-1 w-full items-center justify-center p-4">
                    <LemonBanner
                        type="error"
                        className="max-w-xl"
                        action={{
                            children: 'Retry',
                            onClick: () => setRetryKey((key) => key + 1),
                        }}
                    >
                        This recording failed to render. Retry to load it again, or open another recording.
                    </LemonBanner>
                </div>
            }
        >
            {children}
        </PostHogErrorBoundary>
    )
}
