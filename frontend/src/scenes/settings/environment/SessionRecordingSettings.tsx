import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCalendar, IconCheck, IconClock, IconHourglass, IconInfinity, IconInfo } from '@posthog/icons'
import {
    LemonBanner,
    LemonDialog,
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
import { SESSION_RECORDING_OPT_OUT_SURVEY_ID } from 'lib/constants'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { isObject } from 'lib/utils'
import { getAppContext } from 'lib/utils/getAppContext'
import { organizationLogic } from 'scenes/organizationLogic'
import { InternalMultipleChoiceSurvey } from 'scenes/session-recordings/components/InternalSurvey/InternalMultipleChoiceSurvey'
import { getMaskingConfigFromLevel, getMaskingLevelFromConfig } from 'scenes/session-recordings/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    AccessControlLevel,
    AccessControlResourceType,
    type SessionRecordingMaskingLevel,
    type SessionRecordingRetentionPeriod,
} from '~/types'

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

export function LogCaptureSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
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
                disabledReason={!currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : undefined}
                loading={currentTeamLoading}
            />
        </AccessControlAction>
    )
}

export function CanvasCaptureSettings(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
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
                disabledReason={!currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : undefined}
                loading={currentTeamLoading}
            />
        </AccessControlAction>
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

export function ReplayNetworkCapture(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
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
                disabledReason={!currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : undefined}
                loading={currentTeamLoading}
            />
        </AccessControlAction>
    )
}

export function ReplayNetworkHeadersPayloads(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
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
                            ? 'Session and network performance capture must be enabled'
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
                            ? 'Session and network performance capture must be enabled'
                            : undefined
                    }
                    loading={currentTeamLoading}
                />
            </AccessControlAction>
        </div>
    )
}

/**
 * @deprecated use ReplayTriggers instead, this is only presented to teams that have these settings set
 * @class
 */
export function ReplayAuthorizedDomains(): JSX.Element {
    return (
        <div className="gap-y-2">
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

    const handleOptInChange = (checked: boolean): void => {
        updateCurrentTeam({
            session_recording_opt_in: checked,
        })
        setShowSurvey(!checked)
    }

    return (
        <div>
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
    )
}
