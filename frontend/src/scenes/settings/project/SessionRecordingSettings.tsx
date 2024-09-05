import { IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    Link,
    Spinner,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { FlagSelector } from 'lib/components/FlagSelector'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { PropertySelect } from 'lib/components/PropertySelect/PropertySelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'
import { IconCancel, IconSelectEvents } from 'lib/lemon-ui/icons'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { objectsEqual } from 'lib/utils'
import { sessionReplayLinkedFlagLogic } from 'scenes/settings/project/sessionReplayLinkedFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, MultivariateFlagOptions, SessionRecordingAIConfig } from '~/types'

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
                checked={!!currentTeam?.capture_console_log_opt_in}
                disabledReason={!currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : undefined}
            />
        </div>
    )
}

function CanvasCaptureSettings(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
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
                disabledReason={!currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : undefined}
            />
        </div>
    )
}

function PayloadWarning(): JSX.Element {
    return (
        <>
            <p>
                We automatically scrub some sensitive information from network headers and request and response bodies.
            </p>{' '}
            <p>
                If they could contain sensitive data, you should provide a function to mask the data when you initialise
                PostHog.{' '}
                <Link
                    to="https://posthog.com/docs/session-replay/network-recording#sensitive-information"
                    target="blank"
                >
                    Learn how to mask header and body values in our docs
                </Link>
            </p>
        </>
    )
}

export function NetworkCaptureSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
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
                checked={!!currentTeam?.capture_performance_opt_in}
                disabledReason={!currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : undefined}
            />
            <div className="mt-4">
                <p>
                    When network capture is enabled, we always capture network timings. Use these switches to choose
                    whether to also capture headers and payloads of requests.{' '}
                    <Link to="https://posthog.com/docs/session-replay/network-recording" target="blank">
                        Learn how to mask header and payload values in our docs
                    </Link>
                </p>
                <LemonBanner type="info" className="mb-4">
                    <PayloadWarning />
                </LemonBanner>
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
                            if (checked) {
                                LemonDialog.open({
                                    maxWidth: '650px',
                                    title: 'Network body capture',
                                    description: <PayloadWarning />,
                                    primaryButton: {
                                        'data-attr': 'network-payload-capture-accept-warning-and-enable',
                                        children: 'Enable body capture',
                                        onClick: () => {
                                            updateCurrentTeam({
                                                session_recording_network_payload_capture_config: {
                                                    ...currentTeam?.session_recording_network_payload_capture_config,
                                                    recordBody: true,
                                                },
                                            })
                                        },
                                    },
                                })
                            } else {
                                updateCurrentTeam({
                                    session_recording_network_payload_capture_config: {
                                        ...currentTeam?.session_recording_network_payload_capture_config,
                                        recordBody: false,
                                    },
                                })
                            }
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
            </div>
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

function variantOptions(multivariate: MultivariateFlagOptions | undefined): LemonSegmentedButtonOption<string>[] {
    if (!multivariate) {
        return []
    }
    return [
        {
            label: 'any',
            value: 'any',
        },
        ...multivariate.variants.map((variant) => {
            return {
                label: variant.key,
                value: variant.key,
            }
        }),
    ]
}

function LinkedFlagSelector(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const { hasAvailableFeature } = useValues(userLogic)

    const featureFlagRecordingFeatureEnabled = hasAvailableFeature(AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING)

    const logic = sessionReplayLinkedFlagLogic({ id: currentTeam?.session_recording_linked_flag?.id || null })
    const { linkedFlag, featureFlagLoading, flagHasVariants } = useValues(logic)
    const { selectFeatureFlag } = useActions(logic)

    if (!featureFlagRecordingFeatureEnabled) {
        return null
    }

    return (
        <>
            <div className="flex flex-col space-y-2">
                <LemonLabel className="text-base">
                    Enable recordings using feature flag {featureFlagLoading && <Spinner />}
                </LemonLabel>
                <p>Linking a flag means that recordings will only be collected for users who have the flag enabled.</p>
                <div className="flex flex-row justify-start">
                    <FlagSelector
                        value={currentTeam?.session_recording_linked_flag?.id ?? undefined}
                        onChange={(id, key, flag) => {
                            selectFeatureFlag(flag)
                            updateCurrentTeam({ session_recording_linked_flag: { id, key, variant: null } })
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
                {flagHasVariants && (
                    <>
                        <LemonLabel className="text-base">Link to a specific flag variant</LemonLabel>
                        <LemonSegmentedButton
                            className="min-w-1/3"
                            value={currentTeam?.session_recording_linked_flag?.variant ?? 'any'}
                            options={variantOptions(linkedFlag?.filters.multivariate)}
                            onChange={(variant) => {
                                if (!linkedFlag) {
                                    return
                                }

                                updateCurrentTeam({
                                    session_recording_linked_flag: {
                                        id: linkedFlag?.id,
                                        key: linkedFlag?.key,
                                        variant: variant === 'any' ? null : variant,
                                    },
                                })
                            }}
                        />
                        <p>
                            This is a multi-variant flag. You can link to "any" variant of the flag, and recordings will
                            start whenever the flag is enabled for a user.
                        </p>
                        <p>
                            Alternatively, you can link to a specific variant of the flag, and recordings will only
                            start when the user has that specific variant enabled. Variant targeting support requires
                            posthog-js v1.110.0 or greater
                        </p>
                    </>
                )}
            </div>
        </>
    )
}

export function ReplayCostControl(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const samplingControlFeatureEnabled = hasAvailableFeature(AvailableFeature.SESSION_REPLAY_SAMPLING)
    const recordingDurationMinimumFeatureEnabled = hasAvailableFeature(
        AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM
    )

    return (
        <PayGateMini feature={AvailableFeature.SESSION_REPLAY_SAMPLING}>
            <>
                <p>
                    PostHog offers several tools to let you control the number of recordings you collect and which users
                    you collect recordings for.{' '}
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
                            Use this setting to restrict the percentage of sessions that will be recorded. This is
                            useful if you want to reduce the amount of data you collect. 100% means all sessions will be
                            collected. 50% means roughly half of sessions will be collected.
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
                            value are collected. This helps you avoid collecting sessions that are too short to be
                            useful.
                        </p>
                    </>
                )}
                <LinkedFlagSelector />
            </>
        </PayGateMini>
    )
}

export function ReplayAISettings(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)

    const { currentTeam } = useValues(teamLogic)

    if (!currentTeam) {
        return null
    }

    const defaultConfig = {
        opt_in: false,
        preferred_events: [],
        excluded_events: ['$feature_flag_called'],
        included_event_properties: ['elements_chain', '$window_id', '$current_url', '$event_type'],
        important_user_properties: [],
    }
    const sessionReplayConfig = currentTeam.session_replay_config || {}
    const currentConfig: SessionRecordingAIConfig = sessionReplayConfig.ai_config || defaultConfig

    const updateSummaryConfig = (summaryConfig: SessionRecordingAIConfig): void => {
        updateCurrentTeam({
            session_replay_config: { ai_config: summaryConfig },
        })
    }

    const { opt_in: _discardCurrentOptIn, ...currentComparable } = currentConfig
    const { opt_in: _discardDefaultOptIn, ...defaultComparable } = defaultConfig

    return (
        <div className="flex flex-col gap-2">
            <div>
                <p>
                    We use several machine learning technologies to process sessions. Some of those are powered by{' '}
                    <Link to="https://openai.com/" target="_blank">
                        OpenAI
                    </Link>
                    . No data is sent to OpenAI without an explicit instruction to do so. If we do send data we only
                    send the data selected below. <strong>Data submitted is not used to train OpenAI's models</strong>
                </p>
                <LemonSwitch
                    checked={currentConfig.opt_in}
                    onChange={(checked) => {
                        updateSummaryConfig({
                            ...currentConfig,
                            opt_in: checked,
                        })
                    }}
                    bordered
                    label="Opt in to enable AI processing"
                />
            </div>
            {currentConfig.opt_in && (
                <>
                    {!objectsEqual(currentComparable, defaultComparable) && (
                        <div>
                            <LemonButton
                                type="secondary"
                                onClick={() => updateSummaryConfig({ ...defaultConfig, opt_in: true })}
                            >
                                Reset config to default
                            </LemonButton>
                        </div>
                    )}
                    <div>
                        <h3 className="flex items-center gap-2">
                            <IconSelectEvents className="text-lg" />
                            Preferred events
                        </h3>
                        <p>
                            These events are treated as more interesting when generating a summary. We recommend you
                            include events that represent value for your user
                        </p>
                        <EventSelect
                            onChange={(includedEvents) => {
                                updateSummaryConfig({
                                    ...currentConfig,
                                    preferred_events: includedEvents,
                                })
                            }}
                            selectedEvents={currentConfig.preferred_events || []}
                            addElement={
                                <LemonButton size="small" type="secondary" icon={<IconPlus />} sideIcon={null}>
                                    Add event
                                </LemonButton>
                            }
                        />
                    </div>
                    <div>
                        <h3 className="flex items-center gap-2">
                            <IconSelectEvents className="text-lg" />
                            Excluded events
                        </h3>
                        <p>These events are never submitted even when they are present in the session.</p>
                        <EventSelect
                            onChange={(excludedEvents) => {
                                updateSummaryConfig({
                                    ...currentConfig,
                                    excluded_events: excludedEvents,
                                })
                            }}
                            selectedEvents={currentConfig.excluded_events || []}
                            addElement={
                                <LemonButton size="small" type="secondary" icon={<IconPlus />} sideIcon={null}>
                                    Exclude event
                                </LemonButton>
                            }
                        />
                    </div>
                    <div>
                        <h3 className="flex items-center gap-2">
                            <IconSelectEvents className="text-lg" />
                            Included event properties
                        </h3>
                        <p>
                            We always send the event name and timestamp. The only event data sent are values of the
                            properties selected here.
                        </p>
                        <PropertySelect
                            taxonomicFilterGroup={TaxonomicFilterGroupType.EventProperties}
                            sortable={false}
                            onChange={(properties: string[]) => {
                                updateSummaryConfig({
                                    ...currentConfig,
                                    included_event_properties: properties,
                                })
                            }}
                            selectedProperties={currentConfig.included_event_properties || []}
                            addText="Add property"
                        />
                    </div>
                    <div>
                        <h3 className="flex items-center gap-2">
                            <IconSelectEvents className="text-lg" />
                            Important user properties
                        </h3>
                        <p>
                            We always send the first and last seen dates. The only user data sent are values of the
                            properties selected here.
                        </p>
                        <PropertySelect
                            taxonomicFilterGroup={TaxonomicFilterGroupType.PersonProperties}
                            sortable={false}
                            onChange={(properties) => {
                                updateSummaryConfig({
                                    ...currentConfig,
                                    important_user_properties: properties,
                                })
                            }}
                            selectedProperties={currentConfig.important_user_properties || []}
                            addText="Add property"
                        />
                    </div>
                </>
            )}
        </div>
    )
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
                        })
                    }}
                    label="Record user sessions"
                    bordered
                    checked={!!currentTeam?.session_recording_opt_in}
                />
            </div>
            <LogCaptureSettings />
            <CanvasCaptureSettings />
        </div>
    )
}
