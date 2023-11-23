import { LemonBanner, LemonButton, LemonSelect, LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FlagSelector } from 'lib/components/FlagSelector'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function ReplayGeneral(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)

    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="space-y-4">
            <p>Watch recordings of how users interact with your web app to see what can be improved.</p>

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
                    bordered
                    checked={!!currentTeam?.session_recording_opt_in}
                />

                <p>
                    Please note your website needs to have the{' '}
                    <Link to={urls.settings('project', 'snippet')}>PostHog snippet</Link> or the latest version of{' '}
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
                    bordered
                    checked={currentTeam?.session_recording_opt_in ? !!currentTeam?.capture_console_log_opt_in : false}
                    disabled={!currentTeam?.session_recording_opt_in}
                />
                <p>
                    This setting controls if browser console logs will be captured as a part of recordings. The console
                    logs will be shown in the recording player to help you debug any issues.
                </p>
            </div>
            <div className="space-y-2">
                <NetworkCaptureSettings />
            </div>
        </div>
    )
}

function NetworkCaptureSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)

    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h4>Network capture</h4>
            <LemonSwitch
                data-attr="opt-in-capture-performance-switch"
                onChange={(checked) => {
                    updateCurrentTeam({ capture_performance_opt_in: checked })
                }}
                label="Capture network performance"
                bordered
                checked={currentTeam?.session_recording_opt_in ? !!currentTeam?.capture_performance_opt_in : false}
                disabled={!currentTeam?.session_recording_opt_in}
            />
            <p>
                This setting controls if performance and network information will be captured alongside recordings. The
                network requests and timings will be shown in the recording player to help you debug any issues.
            </p>
            <FlaggedFeature flag={FEATURE_FLAGS.NETWORK_PAYLOAD_CAPTURE} match={true}>
                <h5>Network payloads</h5>
                <div className={'flex flex-row space-x-2'}>
                    <LemonSwitch
                        data-attr="opt-in-capture-network-headers-switch"
                        onChange={(checked) => {
                            updateCurrentTeam({
                                session_recording_network_payload_capture_config: {
                                    ...currentTeam?.session_recording_network_payload_capture_config,
                                    recordHeaders: checked,
                                },
                            })
                        }}
                        label="Capture headers"
                        bordered
                        checked={
                            currentTeam?.session_recording_opt_in
                                ? !!currentTeam?.session_recording_network_payload_capture_config?.recordHeaders
                                : false
                        }
                        disabledReason={
                            !currentTeam?.session_recording_opt_in || !currentTeam?.capture_performance_opt_in
                                ? 'session and network performance capture must be enabled'
                                : undefined
                        }
                    />
                    <LemonSwitch
                        data-attr="opt-in-capture-network-body-switch"
                        onChange={(checked) => {
                            updateCurrentTeam({
                                session_recording_network_payload_capture_config: {
                                    ...currentTeam?.session_recording_network_payload_capture_config,
                                    recordBody: checked,
                                },
                            })
                        }}
                        label="Capture body"
                        bordered
                        checked={
                            currentTeam?.session_recording_opt_in
                                ? !!currentTeam?.session_recording_network_payload_capture_config?.recordBody
                                : false
                        }
                        disabledReason={
                            !currentTeam?.session_recording_opt_in || !currentTeam?.capture_performance_opt_in
                                ? 'session and network performance capture must be enabled'
                                : undefined
                        }
                    />
                </div>
                <p>
                    When network capture is enabled, we always captured network timings. Use these switches to choose
                    whether to capture headers and payloads of requests
                </p>
            </FlaggedFeature>
        </>
    )
}

export function ReplayAuthorizedDomains(): JSX.Element {
    return (
        <div className="space-y-2">
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
    )
}

export function ReplayCostControl(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <FlaggedFeature flag={FEATURE_FLAGS.SESSION_RECORDING_SAMPLING}>
            <>
                <p>
                    PostHog offers several tools to let you control the number of recordings you collect and which users
                    you collect recordings for.{' '}
                    <Link
                        to={'https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record'}
                        target={'blank'}
                    >
                        Learn more in our docs
                    </Link>
                </p>
                <LemonBanner className="mb-4" type={'info'}>
                    Requires posthog-js version 1.88.2 or greater
                </LemonBanner>
                <div className={'flex flex-row justify-between'}>
                    <LemonLabel className="text-base">Sampling</LemonLabel>
                    <LemonSelect
                        onChange={(v) => {
                            updateCurrentTeam({ session_recording_sample_rate: v })
                        }}
                        dropdownMatchSelectWidth={false}
                        options={[
                            {
                                label: '100% (no sampling)',
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
                                label: '85%',
                                value: '0.85',
                            },
                            {
                                label: '80%',
                                value: '0.80',
                            },
                            {
                                label: '75%',
                                value: '0.75',
                            },
                            {
                                label: '70%',
                                value: '0.70',
                            },
                            {
                                label: '65%',
                                value: '0.65',
                            },
                            {
                                label: '60%',
                                value: '0.60',
                            },
                            {
                                label: '55%',
                                value: '0.55',
                            },
                            {
                                label: '50%',
                                value: '0.50',
                            },
                            {
                                label: '45%',
                                value: '0.45',
                            },
                            {
                                label: '40%',
                                value: '0.40',
                            },
                            {
                                label: '35%',
                                value: '0.35',
                            },
                            {
                                label: '30%',
                                value: '0.30',
                            },
                            {
                                label: '25%',
                                value: '0.25',
                            },
                            {
                                label: '20%',
                                value: '0.20',
                            },
                            {
                                label: '15%',
                                value: '0.15',
                            },
                            {
                                label: '10%',
                                value: '0.10',
                            },
                            {
                                label: '5%',
                                value: '0.05',
                            },
                            {
                                label: '0% (replay disabled)',
                                value: '0.00',
                            },
                        ]}
                        value={
                            typeof currentTeam?.session_recording_sample_rate === 'string'
                                ? currentTeam?.session_recording_sample_rate
                                : '1.00'
                        }
                    />
                </div>
                <p>
                    Use this setting to restrict the percentage of sessions that will be recorded. This is useful if you
                    want to reduce the amount of data you collect. 100% means all sessions will be collected. 50% means
                    roughly half of sessions will be collected.
                </p>
                <div className={'flex flex-row justify-between'}>
                    <LemonLabel className="text-base">Minimum session duration (seconds)</LemonLabel>
                    <LemonSelect
                        dropdownMatchSelectWidth={false}
                        onChange={(v) => {
                            updateCurrentTeam({ session_recording_minimum_duration_milliseconds: v })
                        }}
                        options={[
                            {
                                label: 'no minimum',
                                value: null,
                            },
                            {
                                label: '1',
                                value: 1000,
                            },
                            {
                                label: '2',
                                value: 2000,
                            },
                            {
                                label: '5',
                                value: 5000,
                            },
                            {
                                label: '10',
                                value: 10000,
                            },
                            {
                                label: '15',
                                value: 15000,
                            },
                        ]}
                        value={currentTeam?.session_recording_minimum_duration_milliseconds}
                    />
                </div>
                <p>
                    Setting a minimum session duration will ensure that only sessions that last longer than that value
                    are collected. This helps you avoid collecting sessions that are too short to be useful.
                </p>
                <div className={'flex flex-col space-y-2'}>
                    <LemonLabel className="text-base">Enable recordings using feature flag</LemonLabel>
                    <div className={'flex flex-row justify-start space-x-2'}>
                        <FlagSelector
                            value={currentTeam?.session_recording_linked_flag?.id ?? undefined}
                            onChange={(id, key) => {
                                updateCurrentTeam({ session_recording_linked_flag: { id, key } })
                            }}
                        />
                        {currentTeam?.session_recording_linked_flag && (
                            <LemonButton
                                className="ml-2"
                                icon={<IconCancel />}
                                size="small"
                                status="stealth"
                                onClick={() => updateCurrentTeam({ session_recording_linked_flag: null })}
                                title="Clear selected flag"
                            />
                        )}
                    </div>
                </div>
                <p>
                    Linking a flag means that recordings will only be collected for users who have the flag enabled.
                    Only supports release toggles (boolean flags).
                </p>
            </>
        </FlaggedFeature>
    )
}
