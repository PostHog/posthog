import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

export type SessionRecordingSettingsProps = {
    inModal?: boolean
}

export function SessionRecordingSettings({ inModal = false }: SessionRecordingSettingsProps): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <LemonSwitch
                    data-attr="opt-in-session-recording-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            session_recording_opt_in: checked,
                            capture_console_log_opt_in: checked,
                            capture_performance_opt_in: checked,
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
                    This setting controls if performance and network information will be captured alongside recordings.
                    The network requests and timings will be shown in the recording player to help you debug any issues.
                </p>
            </div>
            <FlaggedFeature flag={FEATURE_FLAGS.RECORDINGS_V2_RECORDER} match={true}>
                <div className="space-y-2">
                    <LemonSwitch
                        data-attr="opt-in-capture-performance-switch"
                        onChange={(checked) => {
                            updateCurrentTeam({ session_recording_version: checked ? 'v2' : 'v1' })
                        }}
                        label={
                            <span className="flex items-center gap-2">
                                Use Recorder V2
                                <LemonTag type="warning">Beta</LemonTag>
                            </span>
                        }
                        labelClassName={inModal ? 'text-base font-semibold' : ''}
                        bordered={!inModal}
                        fullWidth={inModal}
                        checked={currentTeam?.session_recording_version === 'v2'}
                    />
                    <p>
                        Turn this setting on to opt into{' '}
                        <Link to="https://github.com/rrweb-io/rrweb/releases/tag/rrweb%402.0.0-alpha.5" target="_blank">
                            rrweb 2
                        </Link>{' '}
                        which comes with various fixes and improvements.
                    </p>
                </div>
            </FlaggedFeature>
            <div className="space-y-2">
                <LemonLabel className="text-base">Authorized domains for recordings</LemonLabel>

                <p>
                    Use the settings below to restrict the domains where recordings will be captured. If no domains are
                    selected, then there will be no domain restriction.
                </p>
                <p>
                    Domains and wildcard subdomains are allowed (e.g. <code>https://*.example.com</code>). However,
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
