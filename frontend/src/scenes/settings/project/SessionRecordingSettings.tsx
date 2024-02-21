import { LemonButton, LemonSelect, LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FlagSelector } from 'lib/components/FlagSelector'
import { FEATURE_FLAGS, SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

function LogCaptureSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div>
            <h3>Log capture</h3>
            <p>
                This setting controls if browser console logs will be captured as a part of recordings. The console logs
                will be shown in the recording player to help you debug any issues.
            </p>
            <LemonSwitch
                data-attr="opt-in-capture-console-log-switch"
                onChange={(checked) => {
                    updateCurrentTeam({ capture_console_log_opt_in: checked })
                }}
                label="Capture console logs"
                bordered
                checked={currentTeam?.session_recording_opt_in ? !!currentTeam?.capture_console_log_opt_in : false}
                disabledReason={
                    !currentTeam?.session_recording_opt_in ? 'session recording must be enabled' : undefined
                }
            />
        </div>
    )
}

function CanvasCaptureSettings(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasCanvasRecording = useFeatureFlag('SESSION_REPLAY_CANVAS')

    return hasCanvasRecording ? (
        <div>
            <h3>Canvas capture</h3>
            <p>
                This setting controls if browser canvas elements will be captured as part of recordings.{' '}
                <b>
                    <i>There is no way to mask canvas elements right now so please make sure they are free of PII.</i>
                </b>
            </p>
            <LemonSwitch
                data-attr="opt-in-capture-canvas-switch"
                onChange={(checked) => {
                    updateCurrentTeam({
                        session_replay_config: {
                            ...currentTeam?.session_replay_config,
                            record_canvas: checked,
                        },
                    })
                }}
                label={
                    <div className="space-x-1">
                        <LemonTag type="success">New</LemonTag>
                        <LemonLabel>Capture canvas elements</LemonLabel>
                    </div>
                }
                bordered
                checked={
                    currentTeam?.session_replay_config ? !!currentTeam?.session_replay_config?.record_canvas : false
                }
                disabledReason={
                    !currentTeam?.session_recording_opt_in ? 'session recording must be enabled' : undefined
                }
            />
        </div>
    ) : null
}

function NetworkCaptureSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div>
            <h3>Network capture</h3>
            <p>
                This setting controls if performance and network information will be captured alongside recordings. The
                network requests and timings will be shown in the recording player to help you debug any issues.
            </p>
            <LemonSwitch
                data-attr="opt-in-capture-performance-switch"
                onChange={(checked) => {
                    updateCurrentTeam({ capture_performance_opt_in: checked })
                }}
                label="Capture network performance"
                bordered
                checked={currentTeam?.session_recording_opt_in ? !!currentTeam?.capture_performance_opt_in : false}
                disabledReason={
                    !currentTeam?.session_recording_opt_in ? 'session recording must be enabled' : undefined
                }
            />
            <FlaggedFeature flag={FEATURE_FLAGS.NETWORK_PAYLOAD_CAPTURE} match={true}>
                <p>
                    When network capture is enabled, we always capture network timings. Use these switches to choose
                    whether to also capture headers and payloads of requests.{' '}
                    <Link to="https://posthog.com/docs/session-replay/network-recording" target="blank">
                        Learn how to mask header and payload values in our docs
                    </Link>
                </p>
                <div className="flex flex-row space-x-2">
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
            </FlaggedFeature>
        </div>
    )
}

function MaskingSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div>
            <h3>Privacy</h3>
            <p>
                {' '}
                Masking allows you to hide sensitive information in recordings. You can learn more in the{' '}
                <Link to="https://posthog.com/docs/session-replay/privacy">privacy docs</Link>.
            </p>
            <p>Any setting in the client overrides this setting.</p>
            <div className="flex flex-row space-x-2">
                <LemonSwitch
                    data-attr="opt-in-mask-inputs-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            session_replay_config: { mask_all_inputs: checked },
                        })
                    }}
                    label="Mask all inputs"
                    bordered
                    checked={
                        currentTeam?.session_recording_opt_in
                            ? currentTeam?.session_replay_config?.mask_all_inputs === undefined
                                ? true
                                : currentTeam?.session_replay_config?.mask_all_inputs
                            : false
                    }
                    tooltip={
                        <>
                            Setting this is equivalent to setting <pre className="inline">mask_all_inputs: true</pre> in
                            your client config.{' '}
                        </>
                    }
                    disabledReason={
                        !currentTeam?.session_recording_opt_in ? 'session recording must be enabled' : undefined
                    }
                />
                <LemonSwitch
                    data-attr="opt-in-mask-text-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            session_replay_config: { mask_all_text: checked },
                        })
                    }}
                    label="Mask all other text"
                    bordered
                    checked={
                        currentTeam?.session_recording_opt_in
                            ? currentTeam?.session_replay_config?.mask_all_text || false
                            : false
                    }
                    tooltip={
                        <>
                            Setting this is equivalent to setting <pre className="inline">maskTextSelector: "*"</pre> in
                            your client config.
                        </>
                    }
                    disabledReason={
                        !currentTeam?.session_recording_opt_in ? 'session recording must be enabled' : undefined
                    }
                />
            </div>
        </div>
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

export function ReplayCostControl(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // some organisations have access to this by virtue of being in a flag
    // other orgs have access by virtue of being on the correct plan
    // having the flag enabled overrides the plan feature check
    const flagIsEnabled = featureFlags[FEATURE_FLAGS.SESSION_RECORDING_SAMPLING]
    const samplingControlFeatureEnabled = flagIsEnabled || hasAvailableFeature(AvailableFeature.SESSION_REPLAY_SAMPLING)
    const recordingDurationMinimumFeatureEnabled =
        flagIsEnabled || hasAvailableFeature(AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM)
    const featureFlagRecordingFeatureEnabled =
        flagIsEnabled || hasAvailableFeature(AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING)

    const canAccessAnyControl =
        samplingControlFeatureEnabled || recordingDurationMinimumFeatureEnabled || featureFlagRecordingFeatureEnabled

    return canAccessAnyControl ? (
        <>
            <p>
                PostHog offers several tools to let you control the number of recordings you collect and which users you
                collect recordings for.{' '}
                <Link
                    to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record"
                    target="blank"
                >
                    Learn more in our docs.
                </Link>
            </p>

            {samplingControlFeatureEnabled && (
                <>
                    <div className="flex flex-row justify-between">
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
                        Use this setting to restrict the percentage of sessions that will be recorded. This is useful if
                        you want to reduce the amount of data you collect. 100% means all sessions will be collected.
                        50% means roughly half of sessions will be collected.
                    </p>
                </>
            )}
            {recordingDurationMinimumFeatureEnabled && (
                <>
                    <div className="flex flex-row justify-between">
                        <LemonLabel className="text-base">Minimum session duration (seconds)</LemonLabel>
                        <LemonSelect
                            dropdownMatchSelectWidth={false}
                            onChange={(v) => {
                                updateCurrentTeam({ session_recording_minimum_duration_milliseconds: v })
                            }}
                            options={SESSION_REPLAY_MINIMUM_DURATION_OPTIONS}
                            value={currentTeam?.session_recording_minimum_duration_milliseconds}
                        />
                    </div>
                    <p>
                        Setting a minimum session duration will ensure that only sessions that last longer than that
                        value are collected. This helps you avoid collecting sessions that are too short to be useful.
                    </p>
                </>
            )}
            {featureFlagRecordingFeatureEnabled && (
                <>
                    <div className="flex flex-col space-y-2">
                        <LemonLabel className="text-base">Enable recordings using feature flag</LemonLabel>
                        <div className="flex flex-row justify-start">
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
                                    type="secondary"
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
            )}
        </>
    ) : null
}

export function ReplayGeneral(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="flex flex-col gap-4">
            <div>
                <p>
                    Watch recordings of how users interact with your web app to see what can be improved.{' '}
                    <Link
                        to="https://posthog.com/docs/user-guides/recordings?utm_campaign=session-recording&utm_medium=in-product"
                        target="_blank"
                    >
                        Check out our docs
                    </Link>
                </p>
                <LemonSwitch
                    data-attr="opt-in-session-recording-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            // when switching replay on or off,
                            // we set defaults for some of the other settings
                            session_recording_opt_in: checked,
                            capture_console_log_opt_in: checked,
                            capture_performance_opt_in: checked,
                        })
                    }}
                    label="Record user sessions"
                    bordered
                    checked={!!currentTeam?.session_recording_opt_in}
                />
            </div>
            <FlaggedFeature flag={FEATURE_FLAGS.REPLAY_REMOTE_MASKING_CONFIG} match={true}>
                <MaskingSettings />
            </FlaggedFeature>
            <LogCaptureSettings />
            <CanvasCaptureSettings />
            <NetworkCaptureSettings />
        </div>
    )
}
