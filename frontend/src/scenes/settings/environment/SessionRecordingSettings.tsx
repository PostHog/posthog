import { IconCheck, IconInfo, IconPlus, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { InternalMultipleChoiceSurvey } from 'lib/components/InternalSurvey/InternalMultipleChoiceSurvey'
import { PropertySelect } from 'lib/components/PropertySelect/PropertySelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS, SESSION_RECORDING_OPT_OUT_SURVEY_ID_2 } from 'lib/constants'
import { IconSelectEvents } from 'lib/lemon-ui/icons'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isObject, objectsEqual } from 'lib/utils'
import { ReactNode, useState } from 'react'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { getMaskingConfigFromLevel, getMaskingLevelFromConfig } from 'scenes/session-recordings/utils'
import { teamLogic } from 'scenes/teamLogic'

import { SessionRecordingAIConfig, type SessionRecordingMaskingLevel } from '~/types'

interface SupportedPlatformProps {
    note?: ReactNode
    label: string
    supportedSinceVersion: false | string
}

function SupportedPlatform(props: SupportedPlatformProps): JSX.Element {
    const node = (
        <div
            className={clsx(
                props.supportedSinceVersion ? 'bg-fill-success-highlight' : 'bg-fill-error-highlight',
                'px-1 py-0.5',
                props.note && props.supportedSinceVersion && 'cursor-pointer'
            )}
        >
            {props.note ? <IconInfo /> : props.supportedSinceVersion ? <IconCheck /> : <IconX />} {props.label}
        </div>
    )
    let tooltip = null
    if (props.supportedSinceVersion || props.note) {
        tooltip = (
            <div className="flex flex-col gap-1">
                {props.supportedSinceVersion && <div>Since version {props.supportedSinceVersion}</div>}
                {props.note && <div>{props.note}</div>}
            </div>
        )
    }
    if (tooltip) {
        return <Tooltip title={tooltip}>{node}</Tooltip>
    }
    return node
}

export function SupportedPlatforms(props: {
    web?: false | { note?: ReactNode; version?: string }
    android?: false | { note?: ReactNode; version?: string }
    ios?: false | { note?: ReactNode; version?: string }
    reactNative?: false | { note?: ReactNode; version?: string }
    flutter?: false | { note?: ReactNode; version?: string }
}): JSX.Element {
    return (
        <div className="text-xs inline-flex flex-row bg-primary rounded items-center border overflow-hidden mb-2 w-fit">
            <span className="px-1 py-0.5 font-semibold">Supported platforms:</span>
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
}

function LogCaptureSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div>
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
            <p>
                This setting controls if browser console logs or app logs will be captured as a part of recordings. The
                logs will be shown in the recording player to help you debug any issues.
            </p>
            <p>
                Log capture is also available for{' '}
                <Link to="https://posthog.com/docs/session-replay/console-log-recording" target="_blank">
                    Mobile session replay
                </Link>{' '}
                , where they can be configured directly in code.
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
            <p>
                This setting controls if browser canvas elements will be captured as part of recordings.{' '}
                <b>
                    <i>There is no way to mask canvas elements right now so please make sure they are free of PII.</i>
                </b>
            </p>
            <p>Canvas capture is only available for JavaScript Web.</p>
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
                    <div className="deprecated-space-x-1">
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

function ZenModeSettings(): JSX.Element | null {
    const { isZenMode } = useValues(playerSettingsLogic)
    const { setIsZenMode } = useActions(playerSettingsLogic)

    return (
        <div>
            <h3>Cinema mode</h3>
            <p>
                This setting controls if cinema mode is enabled. Cinema mode hides all the extra features (e.g.
                annotations, inspector, etc.) and only shows the bare minimum.
            </p>
            <LemonSwitch
                data-attr="opt-in-cinema-mode-switch"
                onChange={setIsZenMode}
                label="Enable cinema mode"
                bordered
                checked={isZenMode}
            />
        </div>
    )
}

export function NetworkCaptureSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <SupportedPlatforms
                android={{ version: '3.1.0' }}
                ios={{ version: '3.12.6' }}
                flutter={false}
                web={{ version: '1.39.0' }}
                reactNative={{ note: <>RN network capture is only supported on iOS</> }}
            />
            <p>
                This setting controls if performance and network information will be captured alongside recordings. The
                network requests and timings will be shown in the recording player to help you debug any issues.
            </p>
            <p>
                Network capture is also available for{' '}
                <Link to="https://posthog.com/docs/session-replay/network-recording" target="_blank">
                    Mobile session replay
                </Link>{' '}
                , where they can be configured directly in code.
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
                <SupportedPlatforms
                    android={false}
                    ios={false}
                    flutter={false}
                    web={{ version: '1.104.4' }}
                    reactNative={false}
                />
                <div className="flex flex-row deprecated-space-x-2">
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

/**
 * @deprecated use ReplayTriggers instead, this is only presented to teams that have these settings set
 * @constructor
 */
export function ReplayAuthorizedDomains(): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            <SupportedPlatforms
                android={false}
                ios={false}
                flutter={false}
                web={{ version: '1.5.0' }}
                reactNative={false}
            />
            <p>
                Use the settings below to restrict the domains where recordings will be captured. If no domains are
                selected, then there will be no domain restriction.
            </p>
            <p>Authorized domains is only available for JavaScript Web.</p>
            <p>
                Domains and wildcard subdomains are allowed (e.g. <code>https://*.example.com</code>). However,
                wildcarded top-level domains cannot be used (for security reasons).
            </p>
            <AuthorizedUrlList type={AuthorizedUrlListType.RECORDING_DOMAINS} />
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
    const { currentTeam } = useValues(teamLogic)

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
            <p>This controls what data is masked during session recordings.</p>
            <p>
                You can configure more advanced settings or change masking for other platforms directly in code.{' '}
                <Link to="https://posthog.com/docs/session-replay/privacy" target="_blank">
                    Learn more
                </Link>
            </p>
            <p>If you specify this in code, it will take precedence over the setting here.</p>
            <LemonSelect
                value={maskingLevel}
                onChange={(val) => val && handleMaskingChange(val)}
                options={[
                    { value: 'total-privacy', label: 'Total privacy (mask all text/images)' },
                    { value: 'normal', label: 'Normal (mask inputs but not text/images)' },
                    { value: 'free-love', label: 'Free love (mask only passwords)' },
                ]}
            />
        </div>
    )
}

export function ReplayGeneral(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const [showSurvey, setShowSurvey] = useState<boolean>(false)
    const { featureFlags } = useValues(featureFlagLogic)

    /**
     * Handle the opt in change
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
                <SupportedPlatforms
                    android={{ version: '3.11.0' }}
                    ios={{ version: '3.19.2' }}
                    flutter={{ version: '4.7.0' }}
                    web={{ version: '1.5.0' }}
                    reactNative={{ version: '3.9.0' }}
                />
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
                        handleOptInChange(checked)
                    }}
                    label="Record user sessions"
                    bordered
                    checked={!!currentTeam?.session_recording_opt_in}
                />
                {showSurvey && <InternalMultipleChoiceSurvey surveyId={SESSION_RECORDING_OPT_OUT_SURVEY_ID_2} />}
            </div>
            <LogCaptureSettings />
            <CanvasCaptureSettings />
            {featureFlags[FEATURE_FLAGS.REPLAY_ZEN_MODE] && <ZenModeSettings />}
        </div>
    )
}
