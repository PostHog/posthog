import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Link } from 'lib/lemon-ui/Link'
import { ReplayCaptureDiagnosticsPanel } from 'scenes/session-recordings/components/ReplayCaptureDiagnosticsPanel'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { TeamPublicType, TeamType } from '~/types'

export type ReplayOptInStatus = 'loading' | 'unknown' | 'enabled' | 'disabled'

/**
 * `session_recording_opt_in` is absent while the team loads, and the public team payload used by
 * shared pages never carries it at all. Neither means replay is off, so both resolve to `unknown`
 * and the page says nothing rather than telling someone with replay running that it is off.
 *
 * A known opt-in wins over an in-flight load, so a background team refresh does not drop a settled
 * banner back to a skeleton.
 */
export function replayOptInStatus(
    currentTeam: TeamType | TeamPublicType | null,
    currentTeamLoading: boolean
): ReplayOptInStatus {
    const optIn = currentTeam?.session_recording_opt_in
    if (optIn !== undefined) {
        return optIn ? 'enabled' : 'disabled'
    }
    return currentTeamLoading ? 'loading' : 'unknown'
}

function ReplayStatusBanner(): JSX.Element | null {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const status = replayOptInStatus(currentTeam, currentTeamLoading)

    if (status === 'loading') {
        return <LemonSkeleton className="mt-4 h-12 max-w-xl mx-auto" />
    }

    if (status === 'unknown') {
        return null
    }

    const enabled = status === 'enabled'

    return (
        <LemonBanner type={enabled ? 'success' : 'warning'} className="mt-4 max-w-xl mx-auto">
            <div className="flex justify-between items-center">
                <div>Session replay is {enabled ? 'enabled' : 'disabled'} for this project</div>
                <LemonButton
                    data-attr="recording-404-edit-settings"
                    type="secondary"
                    size="small"
                    to={urls.settings('project-replay')}
                >
                    Edit settings
                </LemonButton>
            </div>
        </LemonBanner>
    )
}

export function RecordingNotFound({ sessionRecordingId }: { sessionRecordingId?: string }): JSX.Element {
    return (
        <div className="flex flex-col items-center w-full overflow-y-auto">
            <NotFound
                object="Recording"
                className="shrink-0"
                style={sessionRecordingId ? { marginBottom: 0 } : undefined}
                caption={
                    <>
                        The requested recording could not be found. See the diagnosis below for likely reasons, or refer
                        to the{' '}
                        <Link to="https://posthog.com/docs/session-replay/troubleshooting#recording-not-found">
                            troubleshooting guide
                        </Link>
                        .
                        <ReplayStatusBanner />
                    </>
                }
            />
            {sessionRecordingId && (
                <div className="mt-4 mb-12 w-full max-w-xl shrink-0 px-4">
                    <ReplayCaptureDiagnosticsPanel sessionId={sessionRecordingId} />
                </div>
            )}
        </div>
    )
}
