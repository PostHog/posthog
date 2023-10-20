import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { LemonInput, LemonSelect, LemonSwitch, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { SampleRate } from '~/types'

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
                    checked={currentTeam?.session_recording_opt_in ? !!currentTeam?.capture_console_log_opt_in : false}
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
                    checked={currentTeam?.session_recording_opt_in ? !!currentTeam?.capture_performance_opt_in : false}
                    disabled={!currentTeam?.session_recording_opt_in}
                />
                <p>
                    This setting controls if performance and network information will be captured alongside recordings.
                    The network requests and timings will be shown in the recording player to help you debug any issues.
                </p>
            </div>
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
            <FlaggedFeature flag={FEATURE_FLAGS.SESSION_RECORDING_SAMPLING}>
                <>
                    <div className={'flex flex-row justify-between'}>
                        <LemonLabel className="text-base">Sampling</LemonLabel>
                        <LemonSelect
                            onChange={(v) => {
                                updateCurrentTeam({ session_recording_sample_rate: v as SampleRate })
                            }}
                            options={[
                                {
                                    label: '100%',
                                    value: '1.00',
                                },
                                {
                                    label: '95%',
                                    value: '0.95',
                                },
                                {
                                    label: '90%',
                                    value: '0.90',
                                },
                                {
                                    label: '80%',
                                    value: '0.80',
                                },
                                {
                                    label: '50%',
                                    value: '0.50',
                                },
                            ]}
                            value={
                                (typeof currentTeam?.session_recording_sample_rate === 'string'
                                    ? currentTeam?.session_recording_sample_rate
                                    : '1.00') as SampleRate
                            }
                        />
                    </div>
                    <p>
                        Use this setting to restrict the percentage of sessions that will be recorded. This is useful if
                        you want to reduce the amount of data you collect. 100% means all sessions will be collected.
                        50% means roughly half of sessions will be collected.
                    </p>
                </>
            </FlaggedFeature>
            <FlaggedFeature flag={FEATURE_FLAGS.SESSION_RECORDING_SAMPLING}>
                <>
                    <div className={'flex flex-row justify-between'}>
                        <LemonLabel className="text-base">Minimum session duration</LemonLabel>
                        <LemonInput
                            onChange={(v) => {
                                updateCurrentTeam({ session_recording_minimum_duration_milliseconds: v || null })
                            }}
                            type={'number'}
                            allowClear={true}
                        />
                    </div>
                    <p>
                        Setting a minimum session duration will ensure that only sessions that last longer than that
                        value are collected. This helps you avoid collecting sessions that are too short to be useful.
                    </p>
                </>
            </FlaggedFeature>
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
