import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { LemonDivider, LemonSwitch, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonDialog } from 'lib/components/LemonDialog'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'

export function SessionRecordingSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <div className="flex justify-between items-center">
                    <LemonLabel className="text-base ">Record user sessions</LemonLabel>
                    <LemonSwitch
                        data-attr="opt-in-session-recording-switch"
                        onChange={(checked) => {
                            updateCurrentTeam({ session_recording_opt_in: checked })
                        }}
                        checked={!!currentTeam?.session_recording_opt_in}
                    />
                </div>

                <p>
                    Please note your website needs to have the{' '}
                    <Link to={urls.projectSettings() + '#snippet'}>PostHog snippet</Link> or the latest version of{' '}
                    <Link
                        to="https://posthog.com/docs/integrations/js-integration?utm_campaign=session-recording&utm_medium=in-product"
                        target="_blank"
                    >
                        posthog-js
                    </Link>{' '}
                    directly installed. For more details, check out our{' '}
                    <Link
                        to="https://posthog.com/docs/user-guides/recordings?utm_campaign=session-recording&utm_medium=in-product"
                        target="_blank"
                    >
                        docs
                    </Link>
                    .
                </p>
            </div>

            <div className="space-y-2">
                <div className="flex justify-between items-center">
                    <LemonLabel className="text-base">Capture console logs within recordings</LemonLabel>
                    <LemonSwitch
                        data-attr="opt-in-capture-console-log-switch"
                        onChange={(checked) => {
                            updateCurrentTeam({ capture_console_log_opt_in: checked })
                        }}
                        checked={!!currentTeam?.capture_console_log_opt_in}
                        disabled={!currentTeam?.session_recording_opt_in}
                    />
                </div>
                <p>
                    This setting controls if browser console logs wil captured as a part of recordings. The console logs
                    will be shown in the recording player to help you debug any issues.
                </p>
            </div>

            <div className="space-y-2">
                <LemonLabel className="text-base">Authorized domains for recordings</LemonLabel>

                <p>
                    Use the settings below to restrict the domains where recordings will be captured. If no domains are
                    selected, then there will be no domain restriction.
                </p>
                <p>
                    Domains and wilcard subdomains are allowed (e.g. <code>https://*.example.com</code>). However,
                    wildcarded top-level domains cannot be used (for security reasons).
                </p>
                <AuthorizedUrlList type={AuthorizedUrlListType.RECORDING_DOMAINS} />
            </div>
        </div>
    )
}

export function openSessionRecordingSettingsDialog(): void {
    LemonDialog.open({
        title: 'Session recording settings',
        content: <SessionRecordingSettings />,
        width: 600,
        primaryButton: {
            children: 'Done',
        },
    })
}
