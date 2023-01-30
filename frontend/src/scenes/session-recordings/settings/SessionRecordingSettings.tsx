import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonDialog } from 'lib/components/LemonDialog'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export type SessionRecordingSettingsProps = {
    inModal?: boolean
}

export function SessionRecordingSettings({ inModal = false }: SessionRecordingSettingsProps): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <LemonSwitch
                    data-attr="opt-in-session-recording-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            session_recording_opt_in: checked,
                            capture_console_log_opt_in: true,
                            capture_performance_opt_in: true,
                        })
                    }}
                    label="Record user sessions"
                    bordered={!inModal}
                    fullWidth={inModal}
                    labelClassName={inModal ? 'text-base font-semibold' : ''}
                    checked={!!currentTeam?.session_recording_opt_in}
                />

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
                <LemonSwitch
                    data-attr="opt-in-capture-console-log-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({ capture_console_log_opt_in: checked })
                    }}
                    label="Capture console logs"
                    labelClassName={inModal ? 'text-base font-semibold' : ''}
                    bordered={!inModal}
                    fullWidth={inModal}
                    checked={
                        !!currentTeam?.session_recording_opt_in ? !!currentTeam?.capture_console_log_opt_in : false
                    }
                    disabled={!currentTeam?.session_recording_opt_in}
                />
                <p>
                    This setting controls if browser console logs will be captured as a part of recordings. The console
                    logs will be shown in the recording player to help you debug any issues.
                </p>
            </div>

            {featureFlags[FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE] && (
                <div className="space-y-2">
                    <LemonSwitch
                        data-attr="opt-in-capture-performance-switch"
                        onChange={(checked) => {
                            updateCurrentTeam({ capture_performance_opt_in: checked })
                        }}
                        label="Capture network performance"
                        labelClassName={inModal ? 'text-base font-semibold' : ''}
                        bordered={!inModal}
                        fullWidth={inModal}
                        checked={
                            !!currentTeam?.session_recording_opt_in ? !!currentTeam?.capture_performance_opt_in : false
                        }
                        disabled={!currentTeam?.session_recording_opt_in}
                    />
                    <p>
                        This setting controls if performance and network information will be captured alongside
                        recordings. The network requests and timings will be shown in the recording player to help you
                        debug any issues.
                    </p>
                </div>
            )}

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
        content: <SessionRecordingSettings inModal />,
        width: 600,
        primaryButton: {
            children: 'Done',
        },
    })
}
