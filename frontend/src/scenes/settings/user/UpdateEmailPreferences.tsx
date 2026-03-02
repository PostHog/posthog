import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { NotificationSettings, TeamBasicType } from '~/types'

type BooleanNotificationSettings = Omit<
    NotificationSettings,
    'project_weekly_digest_disabled' | 'error_tracking_weekly_digest_project_enabled'
>

const NOTIFICATION_DEFAULTS: BooleanNotificationSettings = {
    plugin_disabled: true,
    error_tracking_issue_assigned: true,
    error_tracking_weekly_digest: true,
    discussions_mentioned: true,
    all_weekly_digest_disabled: false,
    project_api_key_exposed: true,
    materialized_view_sync_failed: false,
}

function ProjectDigestSelector({
    keyPrefix,
    dataAttrPrefix,
    isTeamDisabled,
    onToggleTeam,
    onToggleAllTeams,
    hint,
}: {
    keyPrefix: string
    dataAttrPrefix: string
    isTeamDisabled: (teamId: number) => boolean
    onToggleTeam: (teamId: number, enabled: boolean) => void
    onToggleAllTeams: (teamIds: number[], enabled: boolean) => void
    hint?: string
}): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const [expanded, setExpanded] = useState(true)

    return (
        <div>
            <LemonButton
                icon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                onClick={() => setExpanded(!expanded)}
                size="small"
                type="tertiary"
                className="p-0"
            >
                Select projects ({currentOrganization?.teams?.length || 0} available)
            </LemonButton>

            {expanded && (
                <div className="mt-3 ml-6 space-y-2">
                    {hint && <span className="text-muted text-xs">{hint}</span>}
                    <div className="flex flex-col gap-2">
                        <div className="flex flex-row items-center gap-4">
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={() =>
                                    onToggleAllTeams(
                                        (currentOrganization?.teams || []).map((t: TeamBasicType) => t.id),
                                        true
                                    )
                                }
                            >
                                Enable for all projects
                            </LemonButton>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={() =>
                                    onToggleAllTeams(
                                        (currentOrganization?.teams || []).map((t: TeamBasicType) => t.id),
                                        false
                                    )
                                }
                            >
                                Disable for all projects
                            </LemonButton>
                        </div>

                        {currentOrganization?.teams?.map((team) => (
                            <LemonCheckbox
                                key={`${keyPrefix}-${team.id}`}
                                id={`${keyPrefix}-${team.id}`}
                                data-attr={`${dataAttrPrefix}_${team.id}`}
                                onChange={(checked) => onToggleTeam(team.id, checked)}
                                checked={!isTeamDisabled(team.id)}
                                disabled={userLoading}
                                label={
                                    <div className="flex items-center gap-2">
                                        <span>{team.name}</span>
                                        <LemonTag type="muted">id: {team.id.toString()}</LemonTag>
                                    </div>
                                }
                            />
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}

export function UpdateEmailPreferences(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const {
        updateWeeklyDigestForTeam,
        updateWeeklyDigestForAllTeams,
        updateETWeeklyDigestForTeam,
        updateETWeeklyDigestForAllTeams,
        updateDataPipelineErrorThreshold,
    } = useActions(userLogic)
    const weeklyDigestEnabled = !user?.notification_settings?.all_weekly_digest_disabled
    const etDigestEnabled = user?.notification_settings?.error_tracking_weekly_digest !== false

    const dataPipelineErrorThresholdValue = (user?.notification_settings?.data_pipeline_error_threshold ?? 0) * 100
    const [localDataPipelineErrorThreshold, setLocalDataPipelineErrorThreshold] = useState(
        dataPipelineErrorThresholdValue
    )

    const dataPipelineErrorThresholdError =
        !isNaN(localDataPipelineErrorThreshold) &&
        localDataPipelineErrorThreshold >= 0 &&
        localDataPipelineErrorThreshold <= 100
            ? undefined
            : 'Threshold must be between 0% and 100%'

    return (
        <div className="space-y-3">
            <div className="border rounded p-4">
                <div className="space-y-2">
                    <LemonSwitch
                        data-attr="security_alerts_enabled"
                        checked={true}
                        disabled={true}
                        label="Security alerts"
                    />
                    <span className="text-muted text-sm">
                        Account security notifications including password changes, 2FA, login activity, and personal API
                        key exposure. These notifications cannot be disabled.
                    </span>
                </div>
            </div>

            <div className="border rounded p-4 space-y-3">
                <SimpleSwitch
                    setting="all_weekly_digest_disabled"
                    label="Weekly digest"
                    description="The weekly digest keeps you up to date with everything that's happening in your PostHog organizations"
                    dataAttr="weekly_digest_enabled"
                    inverse={true}
                />

                {weeklyDigestEnabled && (
                    <ProjectDigestSelector
                        keyPrefix="weekly-digest"
                        dataAttrPrefix="weekly_digest"
                        isTeamDisabled={(teamId) =>
                            !!user?.notification_settings.project_weekly_digest_disabled?.[teamId]
                        }
                        onToggleTeam={updateWeeklyDigestForTeam}
                        onToggleAllTeams={updateWeeklyDigestForAllTeams}
                    />
                )}
            </div>

            <div className="border rounded p-4 space-y-3">
                <SimpleSwitch
                    setting="plugin_disabled"
                    label="Data pipeline errors"
                    description="Get notified when data pipeline components (destinations, batch exports) encounter errors for all projects"
                    dataAttr="pipeline_errors_enabled"
                />
                {user?.notification_settings?.plugin_disabled !== false && (
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Failure rate threshold</label>
                        <div className="flex flex-col gap-2">
                            <div className="flex items-center gap-2">
                                <LemonInput
                                    type="number"
                                    size="xsmall"
                                    min={0}
                                    max={100}
                                    step={0.1}
                                    value={localDataPipelineErrorThreshold}
                                    onChange={(value) => {
                                        const numValue = value != null && !isNaN(value) ? value : 0
                                        setLocalDataPipelineErrorThreshold(numValue)
                                        updateDataPipelineErrorThreshold(numValue)
                                    }}
                                    disabledReason={userLoading ? 'Loading...' : undefined}
                                    status={dataPipelineErrorThresholdError ? 'danger' : 'default'}
                                    suffix={<span>%</span>}
                                    className="w-32"
                                />
                                <span className="text-muted text-sm">
                                    Only notify if failure rate exceeds this threshold. Set to 0% to notify on any
                                    failure.
                                </span>
                            </div>
                            {dataPipelineErrorThresholdError && (
                                <div className="text-danger text-sm">{dataPipelineErrorThresholdError}</div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            <div className="border rounded p-4">
                <SimpleSwitch
                    setting="error_tracking_issue_assigned"
                    label="Issue assigned"
                    description="Stay on top of your bugs with a notification every time an issue is assigned to you or your role"
                    dataAttr="error_tracking_issue_assigned_enabled"
                />
            </div>

            <div className="border rounded p-4 space-y-3">
                <SimpleSwitch
                    setting="error_tracking_weekly_digest"
                    label="Error tracking weekly digest"
                    description="Get a weekly summary of exceptions caught across your projects every Monday"
                    dataAttr="error_tracking_weekly_digest_enabled"
                />

                {etDigestEnabled && (
                    <>
                        {!user?.notification_settings.error_tracking_weekly_digest_project_enabled && (
                            <LemonBanner type="info">
                                You haven't selected any projects yet, so on the first digest run we'll automatically
                                pick the one with the most exceptions. If you'd prefer to choose yourself, just select
                                your projects below and we won't override your choice.
                            </LemonBanner>
                        )}
                        <ProjectDigestSelector
                            keyPrefix="et-digest"
                            dataAttrPrefix="et_weekly_digest"
                            isTeamDisabled={(teamId) =>
                                !user?.notification_settings.error_tracking_weekly_digest_project_enabled?.[teamId]
                            }
                            onToggleTeam={updateETWeeklyDigestForTeam}
                            onToggleAllTeams={updateETWeeklyDigestForAllTeams}
                        />
                    </>
                )}
            </div>

            <div className="border rounded p-4">
                <SimpleSwitch
                    setting="discussions_mentioned"
                    label="Comment mentions"
                    description="Get notified when someone mentions you in a discussion on any project"
                    dataAttr="discussions_mentioned_enabled"
                />
            </div>

            <div className="border rounded p-4">
                <SimpleSwitch
                    setting="project_api_key_exposed"
                    label="Private API key exposure"
                    description="Get notified when private API keys are publicly exposed"
                    dataAttr="project_api_key_exposure_enabled"
                />
            </div>

            <div className="border rounded p-4">
                <SimpleSwitch
                    setting="materialized_view_sync_failed"
                    label="Materialized view sync failures"
                    description="Get notified when a materialized view fails to sync"
                    dataAttr="materialized_view_sync_failed_enabled"
                />
            </div>
        </div>
    )
}

const SimpleSwitch = ({
    dataAttr,
    label,
    description,
    setting,
    inverse = false,
}: {
    dataAttr: string
    label: string
    description: string
    setting: keyof BooleanNotificationSettings
    /**
     * Some settings are expressed as "disabled" but the control is expressed as "enabled" (e.g. "All weekly digests" setting).
     */
    inverse?: boolean
}): JSX.Element => {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    const value = user?.notification_settings?.[setting]
    const defaultValue = NOTIFICATION_DEFAULTS[setting]
    let checked: boolean = typeof value === 'boolean' ? value : typeof defaultValue === 'boolean' ? defaultValue : false
    if (inverse) {
        checked = !checked
    }

    return (
        <div className="space-y-2">
            <LemonSwitch
                data-attr={dataAttr}
                onChange={(newChecked) => {
                    user?.notification_settings &&
                        updateUser({
                            notification_settings: {
                                ...user?.notification_settings,
                                [setting]: inverse ? !newChecked : newChecked,
                            },
                        })
                }}
                checked={checked}
                disabled={userLoading}
                label={label}
            />
            <span className="text-muted text-sm">{description}</span>
        </div>
    )
}
