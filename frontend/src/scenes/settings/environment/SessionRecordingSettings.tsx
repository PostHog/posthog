import { useActions, useValues } from 'kea'
import { ReactNode, memo, useMemo, useState } from 'react'

import {
    IconCalendar,
    IconCheck,
    IconClock,
    IconHourglass,
    IconInfinity,
    IconInfo,
    IconPlus,
    IconX,
} from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    LemonSelect,
    LemonSwitch,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { PropertySelect } from 'lib/components/PropertySelect/PropertySelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SESSION_RECORDING_OPT_OUT_SURVEY_ID } from 'lib/constants'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { IconSelectEvents } from 'lib/lemon-ui/icons'
import { isObject, objectsEqual } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { getAppContext } from 'lib/utils/getAppContext'
import { organizationLogic } from 'scenes/organizationLogic'
import { InternalMultipleChoiceSurvey } from 'scenes/session-recordings/components/InternalSurvey/InternalMultipleChoiceSurvey'
import { getMaskingConfigFromLevel, getMaskingLevelFromConfig } from 'scenes/session-recordings/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    AccessControlLevel,
    AccessControlResourceType,
    SessionRecordingAIConfig,
    type SessionRecordingMaskingLevel,
    type SessionRecordingRetentionPeriod,
} from '~/types'

interface SupportedPlatformProps {
    note?: ReactNode
    label: string
    supportedSinceVersion: false | string
}

function SupportedPlatform(props: SupportedPlatformProps): JSX.Element {
    const node = (
        <div
            className={cn(
                props.supportedSinceVersion ? 'bg-fill-success-highlight' : 'bg-fill-warning-highlight',
                'px-1 py-0.5 h-full flex items-center gap-1',
                props.note && props.supportedSinceVersion && 'cursor-help'
            )}
        >
            {props.note ? <IconInfo /> : props.supportedSinceVersion ? <IconCheck /> : <IconX />} {props.label}
        </div>
    )
    let tooltip = null
    if (props.supportedSinceVersion || props.note) {
        tooltip = (
            <div className="flex flex-col gap-1 cursor-help">
                {props.supportedSinceVersion && <div>Since version {props.supportedSinceVersion}</div>}
                {props.note && <div>{props.note}</div>}
            </div>
        )
    }
    if (tooltip) {
        return (
            <Tooltip delayMs={200} title={tooltip}>
                {node}
            </Tooltip>
        )
    }
    return node
}

export const SupportedPlatforms = memo(function SupportedPlatforms(props: {
    web?: false | { note?: ReactNode; version?: string }
    android?: false | { note?: ReactNode; version?: string }
    ios?: false | { note?: ReactNode; version?: string }
    reactNative?: false | { note?: ReactNode; version?: string }
    flutter?: false | { note?: ReactNode; version?: string }
}): JSX.Element | null {
    const allSupported = props && Object.keys(props).length === 5 && Object.values(props).every((value) => !!value)
    return allSupported ? null : (
        <div className="text-xs inline-flex flex-row bg-primary rounded items-center border overflow-hidden mb-2 w-fit">
            <Tooltip delayMs={200} title="We support lots of platforms! But not every feature works everywhere (yet)">
                <span className="px-1 py-0.5 font-semibold cursor-help">Supported platforms:</span>
            </Tooltip>
            <LemonDivider vertical className="h-full" />
            <SupportedPlatform
                note={isObject(props.web) ? props.web.note : undefined}
                label="Web"
                supportedSinceVersion={
                    isObject(props.web) && typeof props.web?.version === 'string' ? props.web.version : false
                }
            />

            <LemonDivider vertical className="h-full" />
            <SupportedPlatform
                note={isObject(props.android) ? props.android.note : undefined}
                label="Android"
                supportedSinceVersion={
                    isObject(props.android) && typeof props.android?.version === 'string'
                        ? props.android.version
                        : false
                }
            />

            <LemonDivider vertical className="h-full" />
            <SupportedPlatform
                note={isObject(props.ios) ? props.ios.note : undefined}
                label="iOS"
                supportedSinceVersion={
                    isObject(props.ios) && typeof props.ios?.version === 'string' ? props.ios.version : false
                }
            />

            <LemonDivider vertical className="h-full" />
            <SupportedPlatform
                note={isObject(props.reactNative) ? props.reactNative.note : undefined}
                label="React Native"
                supportedSinceVersion={
                    isObject(props.reactNative) && typeof props.reactNative?.version === 'string'
                        ? props.reactNative.version
                        : false
                }
            />

            <LemonDivider vertical className="h-full" />
            <SupportedPlatform
                note={isObject(props.flutter) ? props.flutter.note : undefined}
                label="Flutter"
                supportedSinceVersion={
                    isObject(props.flutter) && typeof props.flutter?.version === 'string'
                        ? props.flutter.version
                        : false
                }
            />
        </div>
    )
})

export function Since(props: {
    web?: false | { version?: string }
    android?: false | { version?: string }
    ios?: false | { version?: string }
    reactNative?: false | { version?: string }
    flutter?: false | { version?: string }
}): JSX.Element {
    const tooltipContent = useMemo(() => {
        return Object.entries(props)
            .filter(([_, value]) => !!value)
            .map(([key, value]) => {
                const since = isObject(value) && !!value.version ? <span>since {value.version}</span> : <IconCheck />
                return (
                    <li key={key} className="flex flex-row justify-between gap-x-2">
                        <span>{key}:</span>
                        {since}
                    </li>
                )
            })
    }, [props])

    return (
        <Tooltip delayMs={200} title={<ul>{tooltipContent}</ul>}>
            <IconInfo className="text-muted-alt cursor-help" />
        </Tooltip>
    )
}

function LogCaptureSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
        <div>
            <div className="flex flex-row justify-between">
                <h3>Log capture</h3>
                <SupportedPlatforms
                    android={{ version: '1.0.0' }}
                    ios={{ version: '3.26.0' }}
                    flutter={false}
                    web={{ version: '1.18.0' }}
                    reactNative={{
                        version: '3.9.0',
                        note: <>Android only</>,
                    }}
                />
            </div>
            <p>Show browser or app logs in session recordings to spot issues faster.</p>
            <p>
                <Link to="https://posthog.com/docs/session-replay/console-log-recording" target="_blank">
                    Mobile log capture’s supported too
                </Link>{' '}
                — just set it up in your app’s code.
            </p>
            <AccessControlAction
                resourceType={AccessControlResourceType.SessionRecording}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonSwitch
                    data-attr="opt-in-capture-console-log-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({ capture_console_log_opt_in: checked })
                    }}
                    label="Capture console logs"
                    bordered
                    checked={!!currentTeam?.capture_console_log_opt_in}
                    disabledReason={
                        !currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : undefined
                    }
                    loading={currentTeamLoading}
                />
            </AccessControlAction>
        </div>
    )
}

function CanvasCaptureSettings(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
        <div>
            <div className="flex flex-row justify-between">
                <h3>Canvas capture</h3>
                <SupportedPlatforms
                    android={false}
                    ios={false}
                    flutter={{
                        version: '4.7.0',
                        note: (
                            <>
                                If you're using the <code>canvaskit</code> renderer on Flutter Web, you must also enable
                                canvas capture
                            </>
                        ),
                    }}
                    web={{ version: '1.101.0' }}
                    reactNative={false}
                />
            </div>
            <p>
                This setting controls if browser canvas elements will be captured as part of recordings.{' '}
                <b>
                    <i>There is no way to mask canvas elements right now so please make sure they are free of PII.</i>
                </b>
            </p>
            <AccessControlAction
                resourceType={AccessControlResourceType.SessionRecording}
                minAccessLevel={AccessControlLevel.Editor}
            >
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
                    label={<LemonLabel>Capture canvas elements</LemonLabel>}
                    bordered
                    checked={
                        currentTeam?.session_replay_config ? !!currentTeam?.session_replay_config?.record_canvas : false
                    }
                    disabledReason={
                        !currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : undefined
                    }
                    loading={currentTeamLoading}
                />
            </AccessControlAction>
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
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
        <>
            <div className="flex flex-row justify-between">
                <h3>Capture requests</h3>
                <SupportedPlatforms
                    android={{ version: '3.1.0' }}
                    ios={{ version: '3.12.6' }}
                    flutter={false}
                    web={{ version: '1.39.0' }}
                    reactNative={{ note: <>RN network capture is only supported on iOS</> }}
                />
            </div>
            <p>
                Capture performance and network data with your session recordings. You’ll see requests and timings right
                in the recording player to help debug issues faster. Mobile session replay supports this too —{' '}
                <Link to="https://posthog.com/docs/session-replay/network-recording" target="_blank">
                    just configure it in your app’s code.
                </Link>
            </p>

            <AccessControlAction
                resourceType={AccessControlResourceType.SessionRecording}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonSwitch
                    data-attr="opt-in-capture-performance-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({ capture_performance_opt_in: checked })
                    }}
                    label="Capture network requests"
                    bordered
                    checked={!!currentTeam?.capture_performance_opt_in}
                    disabledReason={
                        !currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : undefined
                    }
                    loading={currentTeamLoading}
                />
            </AccessControlAction>

            <div className="mt-4">
                <div className="flex flex-row justify-between">
                    <h3>Capture headers and payloads</h3>
                    <SupportedPlatforms
                        android={false}
                        ios={false}
                        flutter={false}
                        web={{ version: '1.104.4' }}
                        reactNative={false}
                    />
                </div>
                <p>
                    When network capture’s on, we’ll always record request timings. Use these options to also capture
                    headers and payloads if you need them.{' '}
                    <Link to="https://posthog.com/docs/session-replay/network-recording" target="blank">
                        Learn how to mask header and payload values in our docs
                    </Link>
                </p>

                <div className="flex flex-row gap-x-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonSwitch
                            data-attr="opt-in-capture-network-headers-switch"
                            onChange={(checked) => {
                                if (checked) {
                                    LemonDialog.open({
                                        maxWidth: '650px',
                                        title: 'Network header capture',
                                        description: <PayloadWarning />,
                                        primaryButton: {
                                            'data-attr': 'network-header-capture-accept-warning-and-enable',
                                            children: 'Enable header capture',
                                            onClick: () => {
                                                updateCurrentTeam({
                                                    session_recording_network_payload_capture_config: {
                                                        ...currentTeam?.session_recording_network_payload_capture_config,
                                                        recordHeaders: true,
                                                    },
                                                })
                                            },
                                        },
                                    })
                                } else {
                                    updateCurrentTeam({
                                        session_recording_network_payload_capture_config: {
                                            ...currentTeam?.session_recording_network_payload_capture_config,
                                            recordHeaders: checked,
                                        },
                                    })
                                }
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
                            loading={currentTeamLoading}
                        />
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
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
                            loading={currentTeamLoading}
                        />
                    </AccessControlAction>
                </div>
            </div>
        </>
    )
}

/**
 * @deprecated use ReplayTriggers instead, this is only presented to teams that have these settings set
 * @class
 */
export function ReplayAuthorizedDomains(): JSX.Element {
    return (
        <div className="gap-y-2">
            <SupportedPlatforms
                android={false}
                ios={false}
                flutter={false}
                web={{ version: '1.5.0' }}
                reactNative={false}
            />
            <LemonBanner type="warning">
                <strong>This setting is now deprecated and cannot be updated.</strong> Instead we recommend deleting the
                domains below and using URL triggers in your recording conditions to control which domains you record.
            </LemonBanner>
            <p>
                Domains and wildcard subdomains are allowed (e.g. <code>https://*.example.com</code>). However,
                wildcarded top-level domains cannot be used (for security reasons).
            </p>
            <AuthorizedUrlList type={AuthorizedUrlListType.RECORDING_DOMAINS} showLaunch={false} allowAdd={false} />
        </div>
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

export function ReplayMaskingSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    const handleMaskingChange = (level: SessionRecordingMaskingLevel): void => {
        updateCurrentTeam({
            session_recording_masking_config: getMaskingConfigFromLevel(level),
        })
    }

    const maskingConfig = {
        maskAllInputs: currentTeam?.session_recording_masking_config?.maskAllInputs ?? true,
        maskTextSelector: currentTeam?.session_recording_masking_config?.maskTextSelector,
        blockSelector: currentTeam?.session_recording_masking_config?.blockSelector,
    }

    const maskingLevel = getMaskingLevelFromConfig(maskingConfig)

    return (
        <div>
            <SupportedPlatforms web={{ version: '1.227.0' }} />
            <p>Choose what data gets masked in your session recordings.</p>
            <p>
                For more control (or to adjust masking on other platforms), set it up directly in your code{' '}
                <Link to="https://posthog.com/docs/session-replay/privacy" target="_blank">
                    Learn more
                </Link>
            </p>
            <AccessControlAction
                resourceType={AccessControlResourceType.SessionRecording}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonSelect
                    value={maskingLevel}
                    onChange={(val) => val && handleMaskingChange(val)}
                    options={[
                        { value: 'total-privacy', label: 'Total privacy (mask all text/images)' },
                        { value: 'normal', label: 'Normal (mask inputs but not text/images)' },
                        { value: 'free-love', label: 'Free love (mask only passwords)' },
                    ]}
                    loading={currentTeamLoading}
                />
            </AccessControlAction>
        </div>
    )
}

export function ReplayDataRetentionSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const retentionFeature = currentOrganization?.available_product_features?.find(
        (feature) => feature.key === 'session_replay_data_retention'
    )
    const hasMaxRetentionEntitlement =
        retentionFeature &&
        retentionFeature?.unit?.startsWith('month') &&
        retentionFeature?.limit &&
        retentionFeature?.limit >= 60
    const currentRetention = currentTeam?.session_recording_retention_period || '30d'

    const renderOptions = (loading: boolean): LemonSegmentedButtonOption<SessionRecordingRetentionPeriod>[] => {
        const disabledReason = loading ? 'Loading...' : undefined
        const options = [
            {
                value: '30d' as SessionRecordingRetentionPeriod,
                icon: <IconClock />,
                label: '30 days',
                'data-attr': 'session-recording-retention-button-30d',
                disabledReason,
            },
            {
                value: '90d' as SessionRecordingRetentionPeriod,
                icon: <IconHourglass />,
                label: '90 days',
                disabledReason: 'Only available on the pay-as-you-go plan',
                'data-attr': 'session-recording-retention-button-90d',
            },
            {
                value: '1y' as SessionRecordingRetentionPeriod,
                icon: <IconCalendar />,
                label: '1 year (365 days)',
                disabledReason: 'Only available with the Boost or Scale packages',
                'data-attr': 'session-recording-retention-button-1y',
            },
            {
                value: '5y' as SessionRecordingRetentionPeriod,
                icon: <IconInfinity />,
                label: '5 years (1825 days)',
                disabledReason: 'Only available with the Enterprise package',
                'data-attr': 'session-recording-retention-button-5y',
            },
        ]

        if (
            retentionFeature &&
            retentionFeature?.unit?.startsWith('month') &&
            retentionFeature?.limit &&
            retentionFeature?.limit > 1
        ) {
            if (retentionFeature.limit >= 3) {
                options[1].disabledReason = disabledReason ?? ''
            }

            if (retentionFeature.limit >= 12) {
                options[2].disabledReason = disabledReason ?? ''
            }

            if (retentionFeature.limit >= 60) {
                options[3].disabledReason = disabledReason ?? ''
            }
        }

        return options
    }

    const handleRetentionChange = (retention_period: SessionRecordingRetentionPeriod): void => {
        updateCurrentTeam({
            session_recording_retention_period: retention_period,
        })
    }

    return (
        <div>
            <p>This controls how long your recordings are stored.</p>
            <p>
                Altering this setting will only affect the retention period for future recordings.{' '}
                <Link to="https://posthog.com/docs/session-replay/data-retention" target="_blank">
                    Learn more
                </Link>
            </p>
            <AccessControlAction
                resourceType={AccessControlResourceType.SessionRecording}
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={getAppContext()?.resource_access_control?.[AccessControlResourceType.SessionRecording]}
            >
                <LemonSegmentedButton
                    value={currentRetention}
                    onChange={(val) => val && handleRetentionChange(val)}
                    options={renderOptions(currentTeamLoading)}
                />
            </AccessControlAction>
            {!hasMaxRetentionEntitlement && (
                <p className="mt-4">
                    Need longer data retention? Head over to our{' '}
                    <Link to={urls.organizationBilling()} target="_blank">
                        billing page
                    </Link>{' '}
                    to upgrade your package.{' '}
                </p>
            )}
        </div>
    )
}

export function ReplayGeneral(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const [showSurvey, setShowSurvey] = useState<boolean>(false)

    /**
     * Handle the opt-in change
     * @param checked
     */
    const handleOptInChange = (checked: boolean): void => {
        updateCurrentTeam({
            session_recording_opt_in: checked,
        })

        //If the user opts out, we show the survey
        setShowSurvey(!checked)
    }

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
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonSwitch
                        data-attr="opt-in-session-recording-switch"
                        onChange={(checked) => {
                            handleOptInChange(checked)
                        }}
                        label="Record user sessions"
                        bordered
                        checked={!!currentTeam?.session_recording_opt_in}
                        loading={currentTeamLoading}
                    />
                </AccessControlAction>

                {showSurvey && <InternalMultipleChoiceSurvey surveyId={SESSION_RECORDING_OPT_OUT_SURVEY_ID} />}
            </div>
            <LogCaptureSettings />
            <CanvasCaptureSettings />
        </div>
    )
}
