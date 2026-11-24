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
import { Button, Item, ItemContent, ItemDescription, Text, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

// import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { SESSION_RECORDING_OPT_OUT_SURVEY_ID, TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { isObject } from 'lib/utils/guards'
import { organizationLogic } from 'scenes/organizationLogic'
import { InternalMultipleChoiceSurvey } from 'scenes/session-recordings/components/InternalSurvey/InternalMultipleChoiceSurvey'
import { getMaskingConfigFromLevel, getMaskingLevelFromConfig } from 'scenes/session-recordings/utils'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    type SessionRecordingMaskingConfig,
    type SessionRecordingMaskingLevel,
    type SessionRecordingRetentionPeriod,
} from '~/types'

import { QuillOptionSelect } from './QuillOptionSelect'

const MASKING_LEVEL_OPTIONS: { value: SessionRecordingMaskingLevel; label: string }[] = [
    { value: 'total-privacy', label: 'Total privacy (mask all text/images)' },
    { value: 'normal', label: 'Normal (mask inputs but not text/images)' },
    { value: 'free-love', label: 'Free love (mask only passwords)' },
]

type MobileMaskingKey = keyof NonNullable<SessionRecordingMaskingConfig['mobile']>

const MOBILE_MASKING_SWITCHES: { key: MobileMaskingKey; label: string; dataAttr: string }[] = [
    {
        key: 'maskAllText',
        label: 'Always mask all text in mobile apps',
        dataAttr: 'replay-mobile-mask-all-text-switch',
    },
    {
        key: 'maskAllImages',
        label: 'Always mask all images in mobile apps',
        dataAttr: 'replay-mobile-mask-all-images-switch',
    },
]

const MOBILE_MASKING_HELP =
    "The mobile SDKs mask all text and all images by default. A switch that is on forces that masking, even when your app turns it off in code. A switch that is off leaves the decision to your app's code. These switches can add masking, and they never remove it. Requires a recent version of the mobile SDK."

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
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => {
        updateCurrentTeam({ capture_console_log_opt_in: checked })
    }

    const disabledReason = !currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : restrictedReason

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                dataAttr="opt-in-capture-console-log-switch"
                label="Capture console logs"
                checked={!!currentTeam?.capture_console_log_opt_in}
                onCheckedChange={handleChange}
                disabled={currentTeamLoading}
                disabledReason={disabledReason}
            />
        )
    }

    return (
        <LemonSwitch
            data-attr="opt-in-capture-console-log-switch"
            onChange={handleChange}
            label="Capture console logs"
            bordered
            checked={!!currentTeam?.capture_console_log_opt_in}
            disabledReason={disabledReason}
            loading={currentTeamLoading}
        />
    )
}

export function CanvasCaptureSettings(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => {
        updateCurrentTeam({
            session_replay_config: {
                ...currentTeam?.session_replay_config,
                record_canvas: checked,
            },
        })
    }

    const checked = currentTeam?.session_replay_config ? !!currentTeam?.session_replay_config?.record_canvas : false
    const disabledReason = !currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : restrictedReason

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                dataAttr="opt-in-capture-canvas-switch"
                label="Capture canvas elements"
                checked={checked}
                onCheckedChange={handleChange}
                disabled={currentTeamLoading}
                disabledReason={disabledReason}
            />
        )
    }

    return (
        <LemonSwitch
            data-attr="opt-in-capture-canvas-switch"
            onChange={handleChange}
            label={<LemonLabel>Capture canvas elements</LemonLabel>}
            bordered
            checked={checked}
            disabledReason={disabledReason}
            loading={currentTeamLoading}
        />
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
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => {
        updateCurrentTeam({ capture_performance_opt_in: checked })
    }

    const disabledReason = !currentTeam?.session_recording_opt_in ? 'Session replay must be enabled' : restrictedReason

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                dataAttr="opt-in-capture-performance-switch"
                label="Capture network requests"
                checked={!!currentTeam?.capture_performance_opt_in}
                onCheckedChange={handleChange}
                disabled={currentTeamLoading}
                disabledReason={disabledReason}
            />
        )
    }

    return (
        <LemonSwitch
            data-attr="opt-in-capture-performance-switch"
            onChange={handleChange}
            label="Capture network requests"
            bordered
            checked={!!currentTeam?.capture_performance_opt_in}
            disabledReason={disabledReason}
            loading={currentTeamLoading}
        />
    )
}

export function ReplayNetworkHeadersPayloads(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleHeadersChange = (checked: boolean): void => {
        if (checked) {
            LemonDialog.open({
                maxWidth: '650px',
                title: 'Header capture',
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
    }

    const handleBodyChange = (checked: boolean): void => {
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
    }

    const headersChecked = currentTeam?.session_recording_opt_in
        ? !!currentTeam?.session_recording_network_payload_capture_config?.recordHeaders
        : false
    const bodyChecked = currentTeam?.session_recording_opt_in
        ? !!currentTeam?.session_recording_network_payload_capture_config?.recordBody
        : false
    const disabledReason =
        !currentTeam?.session_recording_opt_in || !currentTeam?.capture_performance_opt_in
            ? 'Session and network performance capture must be enabled'
            : restrictedReason

    if (todayRailNav) {
        return (
            <div className="flex flex-wrap gap-x-6 gap-y-2">
                <QuillSettingSwitch
                    dataAttr="opt-in-capture-network-headers-switch"
                    label="Header capture"
                    checked={headersChecked}
                    onCheckedChange={handleHeadersChange}
                    disabled={currentTeamLoading}
                    disabledReason={disabledReason}
                />
                <QuillSettingSwitch
                    dataAttr="opt-in-capture-network-body-switch"
                    label="Capture body"
                    checked={bodyChecked}
                    onCheckedChange={handleBodyChange}
                    disabled={currentTeamLoading}
                    disabledReason={disabledReason}
                />
            </div>
        )
    }

    return (
        <div className="flex flex-row gap-x-2">
            <LemonSwitch
                data-attr="opt-in-capture-network-headers-switch"
                onChange={handleHeadersChange}
                label="Header capture"
                bordered
                checked={headersChecked}
                disabledReason={disabledReason}
                loading={currentTeamLoading}
            />
            <LemonSwitch
                data-attr="opt-in-capture-network-body-switch"
                onChange={handleBodyChange}
                label="Capture body"
                bordered
                checked={bodyChecked}
                disabledReason={disabledReason}
                loading={currentTeamLoading}
            />
        </div>
    )
}

/**
 * @deprecated use ReplayTriggers instead, this is only presented to teams that have these settings set
 * @class
 */
export function ReplayAuthorizedDomains(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            <strong>This setting is now deprecated and cannot be updated.</strong> Instead we recommend
                            deleting the domains below and using URL triggers in your recording conditions to control
                            which domains you record.
                        </ItemDescription>
                    </ItemContent>
                </Item>
                <Text size="xs" render={<p className="m-0" />}>
                    Domains and wildcard subdomains are allowed (e.g. <code>https://*.example.com</code>). However,
                    wildcarded top-level domains cannot be used (for security reasons).
                </Text>
                <AuthorizedUrlList
                    type={AuthorizedUrlListType.RECORDING_DOMAINS}
                    showLaunch={false}
                    allowAdd={false}
                    displaySuggestions={false}
                />
            </div>
        )
    }

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
            <AuthorizedUrlList
                type={AuthorizedUrlListType.RECORDING_DOMAINS}
                showLaunch={false}
                allowAdd={false}
                displaySuggestions={false}
            />
        </div>
    )
}

export function ReplayMaskingSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

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

    const mobileMasking = currentTeam?.session_recording_masking_config?.mobile

    const handleMobileMaskingChange = (key: MobileMaskingKey, checked: boolean): void => {
        updateCurrentTeam({ session_recording_masking_config: { mobile: { [key]: checked } } })
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-4">
                <QuillOptionSelect
                    value={maskingLevel}
                    options={MASKING_LEVEL_OPTIONS}
                    onChange={handleMaskingChange}
                    disabled={currentTeamLoading}
                    disabledReason={restrictedReason}
                    ariaLabel="Masking level"
                    className="w-fit max-w-full"
                />
                <div className="flex flex-col gap-2">
                    <Text size="xs" weight="semibold" render={<h4 className="m-0" />}>
                        Mobile apps
                    </Text>
                    {MOBILE_MASKING_SWITCHES.map(({ key, label, dataAttr }) => (
                        <QuillSettingSwitch
                            key={key}
                            dataAttr={dataAttr}
                            label={label}
                            checked={mobileMasking?.[key] === true}
                            onCheckedChange={(checked) => handleMobileMaskingChange(key, checked)}
                            disabled={currentTeamLoading}
                            disabledReason={restrictedReason}
                        />
                    ))}
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {MOBILE_MASKING_HELP}
                    </Text>
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <div>
                <LemonSelect
                    value={maskingLevel}
                    onChange={(val) => val && handleMaskingChange(val)}
                    options={MASKING_LEVEL_OPTIONS}
                    loading={currentTeamLoading}
                    disabledReason={restrictedReason}
                />
            </div>
            <div className="flex flex-col gap-2 items-start">
                <LemonLabel>Mobile apps</LemonLabel>
                {MOBILE_MASKING_SWITCHES.map(({ key, label, dataAttr }) => (
                    <LemonSwitch
                        key={key}
                        data-attr={dataAttr}
                        label={label}
                        bordered
                        checked={mobileMasking?.[key] === true}
                        onChange={(checked) => handleMobileMaskingChange(key, checked)}
                        disabledReason={restrictedReason}
                        loading={currentTeamLoading}
                    />
                ))}
                <p className="text-secondary text-xs m-0">{MOBILE_MASKING_HELP}</p>
            </div>
        </div>
    )
}

export function ReplayDataRetentionSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

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
        const disabledReason = loading ? 'Loading...' : (restrictedReason ?? undefined)
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
        if (retention_period === currentRetention) {
            return
        }
        const label = renderOptions(false).find((o) => o.value === retention_period)?.label ?? retention_period
        LemonDialog.open({
            title: 'Change recording retention period?',
            description:
                'Changing retention only affects recordings that start from this point forwards. Existing recordings will keep their original retention period.',
            primaryButton: {
                children: `Change retention to ${label}`,
                onClick: () =>
                    updateCurrentTeam({
                        session_recording_retention_period: retention_period,
                    }),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-4">
                <ToggleGroup
                    className="w-fit flex-wrap"
                    aria-label="Retention period"
                    value={[currentRetention]}
                    onValueChange={(next: string[]) => {
                        if (next[0]) {
                            handleRetentionChange(next[0] as SessionRecordingRetentionPeriod)
                        }
                    }}
                >
                    {renderOptions(currentTeamLoading).map((option) => (
                        <ToggleGroupItem
                            key={option.value}
                            value={option.value}
                            disabledReason={option.disabledReason || (restrictedReason ?? undefined)}
                            data-attr={option['data-attr']}
                        >
                            {option.icon}
                            {option.label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                {!hasMaxRetentionEntitlement && (
                    <Text size="xs" render={<p className="m-0" />}>
                        Need longer data retention? Head over to our{' '}
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.organizationBilling()} target="_blank" />}
                        >
                            billing page
                        </Button>{' '}
                        to upgrade your package.
                    </Text>
                )}
            </div>
        )
    }

    return (
        <div>
            <LemonSegmentedButton
                value={currentRetention}
                onChange={(val) => val && handleRetentionChange(val)}
                options={renderOptions(currentTeamLoading)}
                disabledReason={restrictedReason ?? undefined}
            />
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
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleOptInChange = (checked: boolean): void => {
        updateCurrentTeam({
            session_recording_opt_in: checked,
        })
        setShowSurvey(!checked)
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-4">
                <QuillSettingSwitch
                    dataAttr="opt-in-session-recording-switch"
                    label="Record user sessions"
                    checked={!!currentTeam?.session_recording_opt_in}
                    onCheckedChange={handleOptInChange}
                    disabled={currentTeamLoading}
                    disabledReason={restrictedReason}
                />
                {showSurvey && <InternalMultipleChoiceSurvey surveyId={SESSION_RECORDING_OPT_OUT_SURVEY_ID} />}
            </div>
        )
    }

    return (
        <div>
            <LemonSwitch
                data-attr="opt-in-session-recording-switch"
                onChange={(checked) => {
                    handleOptInChange(checked)
                }}
                label="Record user sessions"
                bordered
                checked={!!currentTeam?.session_recording_opt_in}
                loading={currentTeamLoading}
                disabledReason={restrictedReason}
            />

            {showSurvey && <InternalMultipleChoiceSurvey surveyId={SESSION_RECORDING_OPT_OUT_SURVEY_ID} />}
        </div>
    )
}
