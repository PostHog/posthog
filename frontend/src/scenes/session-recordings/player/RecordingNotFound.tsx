import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function RecordingNotFound(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <NotFound
            object="Recording"
            caption={
                <>
                    The requested recording doesn't seem to exist. The recording may still be processing, deleted due to
                    age or have not been enabled. Please check your{' '}
                    <Link to={urls.settings('project-replay')}>project settings</Link> that recordings is turned on and
                    enabled for the domain in question. Alternatively read the{' '}
                    <Link to="https://posthog.com/docs/session-replay/troubleshooting#recording-not-found">
                        troubleshooting guide
                    </Link>
                    {currentTeam?.session_recording_opt_in ? (
                        <LemonBanner type="info" className="mt-4 max-w-xl mx-auto">
                            <div className="justify-between flex items-center">
                                <p>Session replay is enabled for this project</p>
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
                            <div className="justify-between flex items-center">
                                <p>Session replay is disabled for this project</p>
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
    )
}
