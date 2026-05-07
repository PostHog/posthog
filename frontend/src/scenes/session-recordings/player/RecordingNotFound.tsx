import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { ReplayCaptureDiagnosticsPanel } from 'scenes/session-recordings/components/ReplayCaptureDiagnosticsPanel'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function RecordingNotFound({ sessionRecordingId }: { sessionRecordingId?: string }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="flex flex-col items-center w-full overflow-y-auto">
            <NotFound
                object="Recording"
                caption={
                    <>
                        The requested recording could not be found. See the diagnosis below for likely reasons, or refer
                        to the{' '}
                        <Link to="https://posthog.com/docs/session-replay/troubleshooting#recording-not-found">
                            troubleshooting guide
                        </Link>
                        .
                        {currentTeam?.session_recording_opt_in ? (
                            <LemonBanner type="success" className="mt-4 max-w-xl mx-auto">
                                <div className="flex justify-between items-center">
                                    <div>Session replay is enabled for this project</div>
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
                        ) : (
                            <LemonBanner type="warning" className="mt-4 max-w-xl mx-auto">
                                <div className="flex justify-between items-center">
                                    <div>Session replay is disabled for this project</div>
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
                        )}
                    </>
                }
            />
            {sessionRecordingId && (
                <div className="-mt-16 mb-12 w-full max-w-xl px-4">
                    <ReplayCaptureDiagnosticsPanel sessionId={sessionRecordingId} />
                </div>
            )}
        </div>
    )
}
