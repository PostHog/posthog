import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconQuestion } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonSwitch,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, NotificationSettings, OrganizationBasicType, TeamBasicType } from '~/types'

import { LOCKED_BY_ORGANIZATION, lockedDisabledReason, lockedValueFor } from '../shared/notificationLocks'
import {
    APPROVALS_TOOLTIP,
    DATA_PIPELINE_THRESHOLD_DESCRIPTION,
    ET_DIGEST_AUTO_PICK_NOTICE,
    MEMBER_JOIN_DESCRIPTION,
    MEMBER_JOIN_HINT,
    PIPELINE_HINT,
    SECURITY_ALERTS_DESCRIPTION,
    WA_DIGEST_AUTO_PICK_NOTICE,
} from './emailPreferencesCopy'
import { NotificationCard } from './NotificationCard'
import { PIPELINE_KIND_LABELS, pipelineNotificationsLogic } from './pipelineNotificationsLogic'
import { QuillApprovalsHeading } from './QuillApprovalsHeading'
import { QuillDataPipelineErrorThreshold } from './QuillDataPipelineErrorThreshold'
import { QuillInfoNotice } from './QuillInfoNotice'
import { QuillMemberJoinHeading } from './QuillMemberJoinHeading'
import { QuillNotificationSwitch } from './QuillNotificationSwitch'
import { QuillOrganizationMemberJoinSelector } from './QuillOrganizationMemberJoinSelector'
import { QuillPipelineNotificationSelector } from './QuillPipelineNotificationSelector'
import { QuillProjectDigestSelector } from './QuillProjectDigestSelector'
import { QuillSecurityAlertsSwitch } from './QuillSecurityAlertsSwitch'
import { QuillUpdateEmailPreferences } from './QuillUpdateEmailPreferences'

enum NotificationBlock {
    Security = 'security',
    WeeklyDigest = 'weekly-digest',
    MemberJoin = 'member-join',
    DataPipelineErrors = 'data-pipeline-errors',
    IssueAssigned = 'issue-assigned',
    EtWeeklyDigest = 'et-weekly-digest',
    WaWeeklyDigest = 'wa-weekly-digest',
    DataCatalogWeeklyDigest = 'data-catalog-weekly-digest',
    CommentMentions = 'comment-mentions',
    Approvals = 'approvals',
    ApiKeyExposure = 'api-key-exposure',
    MaterializedViewSync = 'materialized-view-sync',
    AiEvaluationDisabled = 'ai-evaluation-disabled',
    WorkflowSuggestions = 'workflow-suggestions',
}

const NOTIFICATION_BLOCK_ORDER = Object.values(NotificationBlock)

type BooleanNotificationSettings = Omit<
    NotificationSettings,
    | 'project_weekly_digest_disabled'
    | 'error_tracking_weekly_digest_project_enabled'
    | 'web_analytics_weekly_digest_project_enabled'
    | 'organization_member_join_email_disabled'
>

const NOTIFICATION_DEFAULTS: BooleanNotificationSettings = {
    plugin_disabled: true,
    error_tracking_issue_assigned: true,
    error_tracking_weekly_digest: true,
    discussions_mentioned: true,
    all_weekly_digest_disabled: false,
    project_api_key_exposed: true,
    ai_evaluation_disabled: true,
    workflow_suggestions: true,
    materialized_view_sync_failed: false,
    materialized_view_sync_failed_daily: true,
    materialized_view_sync_failed_immediate: false,
    web_analytics_weekly_digest: true,
    data_catalog_weekly_digest: true,
    approval_requested: true,
    approval_resolved: true,
}

function ProjectDigestSelector({
    keyPrefix,
    dataAttrPrefix,
    setting,
    inverse = false,
    isTeamDisabled,
    onToggleTeam,
    onToggleAllTeams,
    hint,
}: {
    keyPrefix: string
    dataAttrPrefix: string
    /** The setting an organization admin can enforce per project. */
    setting: string
    /** True when the stored value means "off", so an enforced value reads inverted. */
    inverse?: boolean
    isTeamDisabled: (teamId: number) => boolean
    onToggleTeam: (teamId: number, enabled: boolean) => void
    onToggleAllTeams: (teamIds: number[], enabled: boolean) => void
    hint?: string
}): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const [expanded, setExpanded] = useState(true)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const teams = currentOrganization?.teams ?? []
    const ownTeamIds = teams
        .filter((team: TeamBasicType) => lockedValueFor(user?.notification_locks, setting, team.id) === null)
        .map((team: TeamBasicType) => team.id)

    const isTeamChecked = (teamId: number, enforced: boolean | null): boolean =>
        enforced !== null ? (inverse ? !enforced : enforced) : !isTeamDisabled(teamId)

    if (todayRailNav) {
        return (
            <QuillProjectDigestSelector
                teams={teams}
                keyPrefix={keyPrefix}
                dataAttrPrefix={dataAttrPrefix}
                expanded={expanded}
                onExpandedChange={setExpanded}
                hint={hint}
                enforcedFor={(teamId) => lockedValueFor(user?.notification_locks, setting, teamId)}
                isTeamChecked={isTeamChecked}
                userLoading={userLoading}
                onToggleTeam={onToggleTeam}
                onEnableAll={() => onToggleAllTeams(ownTeamIds, true)}
                onDisableAll={() => onToggleAllTeams(ownTeamIds, false)}
                bulkDisabledReason={ownTeamIds.length === 0 ? LOCKED_BY_ORGANIZATION : undefined}
            />
        )
    }

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
                                onClick={() => onToggleAllTeams(ownTeamIds, true)}
                                disabledReason={ownTeamIds.length === 0 ? LOCKED_BY_ORGANIZATION : undefined}
                            >
                                Enable for all projects
                            </LemonButton>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={() => onToggleAllTeams(ownTeamIds, false)}
                                disabledReason={ownTeamIds.length === 0 ? LOCKED_BY_ORGANIZATION : undefined}
                            >
                                Disable for all projects
                            </LemonButton>
                        </div>

                        {teams.map((team: TeamBasicType) => {
                            const enforced = lockedValueFor(user?.notification_locks, setting, team.id)
                            return (
                                <LemonCheckbox
                                    key={`${keyPrefix}-${team.id}`}
                                    id={`${keyPrefix}-${team.id}`}
                                    data-attr={`${dataAttrPrefix}_${team.id}`}
                                    onChange={(checked) => onToggleTeam(team.id, checked)}
                                    checked={isTeamChecked(team.id, enforced)}
                                    disabledReason={lockedDisabledReason(enforced, userLoading)}
                                    label={
                                        <div className="flex items-center gap-2">
                                            <span>{team.name}</span>
                                            <LemonTag type="muted">id: {team.id.toString()}</LemonTag>
                                            {enforced !== null && (
                                                <LemonTag type="highlight">Set by your admin</LemonTag>
                                            )}
                                        </div>
                                    }
                                />
                            )
                        })}
                    </div>
                </div>
            )}
        </div>
    )
}

function OrganizationMemberJoinSelector(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateMemberJoinEmailForOrganization, updateMemberJoinEmailForAllOrganizations } = useActions(userLogic)
    const [expanded, setExpanded] = useState(true)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const organizations = [...(user?.organizations || [])].sort((a, b) => a.name.localeCompare(b.name))

    const isOrgDisabled = (orgId: string): boolean =>
        !!user?.notification_settings?.organization_member_join_email_disabled?.[orgId]
    const enforcedFor = (orgId: string): boolean | null =>
        lockedValueFor(user?.notification_locks, 'organization_member_join_email_disabled', orgId)
    const ownOrgIds = organizations.filter((o: OrganizationBasicType) => enforcedFor(o.id) === null).map((o) => o.id)
    const isOrgChecked = (orgId: string, enforced: boolean | null): boolean =>
        enforced !== null ? !enforced : !isOrgDisabled(orgId)

    if (todayRailNav) {
        return (
            <QuillOrganizationMemberJoinSelector
                organizations={organizations}
                expanded={expanded}
                onExpandedChange={setExpanded}
                enforcedFor={enforcedFor}
                isOrgChecked={isOrgChecked}
                userLoading={userLoading}
                onToggleOrganization={updateMemberJoinEmailForOrganization}
                onEnableAll={() => updateMemberJoinEmailForAllOrganizations(ownOrgIds, true)}
                onDisableAll={() => updateMemberJoinEmailForAllOrganizations(ownOrgIds, false)}
                bulkDisabledReason={ownOrgIds.length === 0 ? LOCKED_BY_ORGANIZATION : undefined}
            />
        )
    }

    return (
        <div>
            <LemonButton
                icon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                onClick={() => setExpanded(!expanded)}
                size="small"
                type="tertiary"
                className="p-0"
            >
                Select organizations ({organizations.length} available)
            </LemonButton>

            {expanded && (
                <div className="mt-3 ml-6 space-y-2">
                    <span className="text-muted text-xs">{MEMBER_JOIN_HINT}</span>
                    <div className="flex flex-col gap-2">
                        <div className="flex flex-row items-center gap-4">
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={() => updateMemberJoinEmailForAllOrganizations(ownOrgIds, true)}
                                disabledReason={ownOrgIds.length === 0 ? LOCKED_BY_ORGANIZATION : undefined}
                            >
                                Enable for all organizations
                            </LemonButton>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={() => updateMemberJoinEmailForAllOrganizations(ownOrgIds, false)}
                                disabledReason={ownOrgIds.length === 0 ? LOCKED_BY_ORGANIZATION : undefined}
                            >
                                Disable for all organizations
                            </LemonButton>
                        </div>

                        {organizations.map((org) => {
                            const enforced = enforcedFor(org.id)
                            return (
                                <LemonCheckbox
                                    key={`member-join-org-${org.id}`}
                                    id={`member-join-org-${org.id}`}
                                    data-attr={`member_join_email_org_${org.id}`}
                                    onChange={(checked) => updateMemberJoinEmailForOrganization(org.id, checked)}
                                    checked={isOrgChecked(org.id, enforced)}
                                    disabledReason={lockedDisabledReason(enforced, userLoading)}
                                    label={
                                        <span className="flex items-center gap-2">
                                            {org.name}
                                            {enforced !== null && (
                                                <LemonTag type="highlight">Set by your admin</LemonTag>
                                            )}
                                        </span>
                                    }
                                />
                            )
                        })}
                    </div>
                </div>
            )}
        </div>
    )
}

function PipelineNotificationSelector(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updatePipelineNotification, updatePipelineNotificationForAll } = useActions(userLogic)
    const { pipelines, pipelinesLoading, pipelinesByTeam, allPipelineIds, isPipelineDisabled } =
        useValues(pipelineNotificationsLogic)
    const [expanded, setExpanded] = useState(false)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const isPipelineChecked = (pipelineId: string, enforced: boolean | null): boolean =>
        enforced !== null ? !enforced : !isPipelineDisabled(pipelineId)

    if (todayRailNav) {
        return (
            <QuillPipelineNotificationSelector
                expanded={expanded}
                onExpandedChange={setExpanded}
                pipelines={pipelines}
                pipelinesLoading={pipelinesLoading}
                pipelinesByTeam={pipelinesByTeam}
                enforcedFor={(teamId) =>
                    lockedValueFor(user?.notification_locks, 'pipeline_notifications_disabled', teamId)
                }
                isPipelineChecked={isPipelineChecked}
                userLoading={userLoading}
                onTogglePipeline={updatePipelineNotification}
                onEnableAll={() => updatePipelineNotificationForAll(allPipelineIds, true)}
                onDisableAll={() => updatePipelineNotificationForAll(allPipelineIds, false)}
            />
        )
    }

    return (
        <div>
            <LemonButton
                icon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                onClick={() => setExpanded(!expanded)}
                size="small"
                type="tertiary"
                className="p-0"
            >
                Select pipelines to receive notifications for
            </LemonButton>

            {expanded && (
                <div className="mt-3 ml-6 space-y-2">
                    <p className="text-muted text-xs">{PIPELINE_HINT}</p>
                    {pipelinesLoading ? (
                        <div className="flex items-center gap-2 py-2">
                            <Spinner className="text-lg" />
                            <span className="text-muted text-sm">Loading pipelines...</span>
                        </div>
                    ) : pipelines.length === 0 ? (
                        <p className="text-muted text-sm">No pipelines found in your projects.</p>
                    ) : (
                        <div className="flex flex-col gap-2">
                            <div className="flex flex-row items-center gap-4">
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() => updatePipelineNotificationForAll(allPipelineIds, true)}
                                >
                                    Enable all notifications
                                </LemonButton>
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() => updatePipelineNotificationForAll(allPipelineIds, false)}
                                >
                                    Mute all notifications
                                </LemonButton>
                            </div>

                            {Object.entries(pipelinesByTeam).map(([key, { teamId, teamName, items }]) => {
                                const enforced = lockedValueFor(
                                    user?.notification_locks,
                                    'pipeline_notifications_disabled',
                                    teamId
                                )
                                return (
                                    <div key={key} className="flex flex-col gap-2">
                                        <div className="flex items-center gap-2">
                                            <span className="font-medium">{teamName}</span>
                                            <LemonTag type="muted">id: {teamId}</LemonTag>
                                            {enforced !== null && (
                                                <LemonTag type="highlight">Set by your admin</LemonTag>
                                            )}
                                        </div>
                                        <div className="ml-4 flex flex-col gap-1">
                                            {items.map((pipeline) => (
                                                <LemonCheckbox
                                                    key={pipeline.id}
                                                    id={`pipeline-${pipeline.id}`}
                                                    data-attr={`pipeline_notification_${pipeline.id}`}
                                                    onChange={(checked) =>
                                                        updatePipelineNotification(pipeline.id, checked)
                                                    }
                                                    checked={isPipelineChecked(pipeline.id, enforced)}
                                                    disabledReason={lockedDisabledReason(enforced, userLoading)}
                                                    label={
                                                        <div className="flex items-center gap-2">
                                                            <span>{pipeline.name}</span>
                                                            <LemonTag type="default">
                                                                {PIPELINE_KIND_LABELS[pipeline.kind]}
                                                            </LemonTag>
                                                        </div>
                                                    }
                                                />
                                            ))}
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export function UpdateEmailPreferences(): JSX.Element {
    const { user, userLoading, hasAvailableFeature } = useValues(userLogic)
    const {
        updateWeeklyDigestForTeam,
        updateWeeklyDigestForAllTeams,
        updateETWeeklyDigestForTeam,
        updateETWeeklyDigestForAllTeams,
        updateWAWeeklyDigestForTeam,
        updateWAWeeklyDigestForAllTeams,
        updateDataPipelineErrorThreshold,
    } = useActions(userLogic)
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { searchParams } = useValues(router)
    const highlight = searchParams.highlight as NotificationBlock | undefined
    const dataLoaded = !userLoading && !currentOrganizationLoading && !!user && !!currentOrganization

    const weeklyDigestEnabled = !user?.notification_settings?.all_weekly_digest_disabled
    const etDigestEnabled = user?.notification_settings?.error_tracking_weekly_digest !== false
    const waDigestEnabled = user?.notification_settings?.web_analytics_weekly_digest !== false

    const dataPipelineErrorThresholdValue = (user?.notification_settings?.data_pipeline_error_threshold ?? 0) * 100
    const [localDataPipelineErrorThreshold, setLocalDataPipelineErrorThreshold] = useState(
        dataPipelineErrorThresholdValue
    )
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleDataPipelineErrorThresholdChange = (value: number | undefined): void => {
        const numValue = value != null && !isNaN(value) ? value : 0
        setLocalDataPipelineErrorThreshold(numValue)
        updateDataPipelineErrorThreshold(numValue)
    }

    const dataPipelineErrorThresholdError =
        !isNaN(localDataPipelineErrorThreshold) &&
        localDataPipelineErrorThreshold >= 0 &&
        localDataPipelineErrorThreshold <= 100
            ? undefined
            : 'Threshold must be between 0% and 100%'

    const blocks: Record<NotificationBlock, JSX.Element> = {
        [NotificationBlock.Security]: (
            <NotificationCard lemonClassName="border rounded p-4">
                {todayRailNav ? (
                    <QuillSecurityAlertsSwitch />
                ) : (
                    <div className="space-y-2">
                        <LemonSwitch
                            data-attr="security_alerts_enabled"
                            checked={true}
                            disabled={true}
                            label="Security alerts"
                        />
                        <span className="text-muted text-sm">{SECURITY_ALERTS_DESCRIPTION}</span>
                    </div>
                )}
            </NotificationCard>
        ),
        [NotificationBlock.WeeklyDigest]: (
            <NotificationCard lemonClassName="border rounded p-4 space-y-3">
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
                        setting="project_weekly_digest_disabled"
                        inverse
                        isTeamDisabled={(teamId) =>
                            !!user?.notification_settings.project_weekly_digest_disabled?.[teamId]
                        }
                        onToggleTeam={updateWeeklyDigestForTeam}
                        onToggleAllTeams={updateWeeklyDigestForAllTeams}
                    />
                )}
            </NotificationCard>
        ),
        [NotificationBlock.MemberJoin]: (
            <NotificationCard lemonClassName="border rounded p-4 space-y-3">
                {todayRailNav ? (
                    <QuillMemberJoinHeading />
                ) : (
                    <div className="space-y-2">
                        <span className="font-medium">New member joined</span>
                        <span className="text-muted text-sm block">{MEMBER_JOIN_DESCRIPTION}</span>
                    </div>
                )}
                <OrganizationMemberJoinSelector />
            </NotificationCard>
        ),
        [NotificationBlock.DataPipelineErrors]: (
            <NotificationCard lemonClassName="border rounded p-4 space-y-3">
                <SimpleSwitch
                    setting="plugin_disabled"
                    label="Data pipeline errors"
                    description="Get notified when data pipeline components (destinations, batch exports, data warehouse sources) encounter errors for all projects"
                    dataAttr="pipeline_errors_enabled"
                />
                {user?.notification_settings?.plugin_disabled !== false &&
                    (todayRailNav ? (
                        <QuillDataPipelineErrorThreshold
                            value={localDataPipelineErrorThreshold}
                            onChange={handleDataPipelineErrorThresholdChange}
                            error={dataPipelineErrorThresholdError}
                            disabled={userLoading}
                        />
                    ) : (
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
                                        onChange={handleDataPipelineErrorThresholdChange}
                                        disabledReason={userLoading ? 'Loading...' : undefined}
                                        status={dataPipelineErrorThresholdError ? 'danger' : 'default'}
                                        suffix={<span>%</span>}
                                        className="w-32"
                                    />
                                    <span className="text-muted text-sm">{DATA_PIPELINE_THRESHOLD_DESCRIPTION}</span>
                                </div>
                                {dataPipelineErrorThresholdError && (
                                    <div className="text-danger text-sm">{dataPipelineErrorThresholdError}</div>
                                )}
                            </div>
                        </div>
                    ))}
                {user?.notification_settings?.plugin_disabled !== false && <PipelineNotificationSelector />}
            </NotificationCard>
        ),
        [NotificationBlock.IssueAssigned]: (
            <NotificationCard lemonClassName="border rounded p-4">
                <SimpleSwitch
                    setting="error_tracking_issue_assigned"
                    label="Issue assigned"
                    description="Stay on top of your bugs with a notification every time an issue is assigned to you or your role"
                    dataAttr="error_tracking_issue_assigned_enabled"
                />
            </NotificationCard>
        ),
        [NotificationBlock.EtWeeklyDigest]: (
            <NotificationCard lemonClassName="border rounded p-4 space-y-3">
                <SimpleSwitch
                    setting="error_tracking_weekly_digest"
                    label="Error tracking weekly digest"
                    description="Get a weekly summary of exceptions caught across your projects every Monday"
                    dataAttr="error_tracking_weekly_digest_enabled"
                />
                {etDigestEnabled && (
                    <>
                        {!user?.notification_settings.error_tracking_weekly_digest_project_enabled &&
                            (todayRailNav ? (
                                <QuillInfoNotice>{ET_DIGEST_AUTO_PICK_NOTICE}</QuillInfoNotice>
                            ) : (
                                <LemonBanner type="info">{ET_DIGEST_AUTO_PICK_NOTICE}</LemonBanner>
                            ))}
                        <ProjectDigestSelector
                            keyPrefix="et-digest"
                            dataAttrPrefix="et_weekly_digest"
                            setting="error_tracking_weekly_digest_project_enabled"
                            isTeamDisabled={(teamId) =>
                                !user?.notification_settings.error_tracking_weekly_digest_project_enabled?.[teamId]
                            }
                            onToggleTeam={updateETWeeklyDigestForTeam}
                            onToggleAllTeams={updateETWeeklyDigestForAllTeams}
                        />
                    </>
                )}
            </NotificationCard>
        ),
        [NotificationBlock.WaWeeklyDigest]: (
            <NotificationCard lemonClassName="border rounded p-4 space-y-3">
                <SimpleSwitch
                    setting="web_analytics_weekly_digest"
                    label="Web analytics weekly digest"
                    description="Get a weekly summary of web traffic across your projects every Monday"
                    dataAttr="web_analytics_weekly_digest_enabled"
                />
                {waDigestEnabled && (
                    <>
                        {!user?.notification_settings.web_analytics_weekly_digest_project_enabled &&
                            (todayRailNav ? (
                                <QuillInfoNotice>{WA_DIGEST_AUTO_PICK_NOTICE}</QuillInfoNotice>
                            ) : (
                                <LemonBanner type="info">{WA_DIGEST_AUTO_PICK_NOTICE}</LemonBanner>
                            ))}
                        <ProjectDigestSelector
                            keyPrefix="wa-digest"
                            dataAttrPrefix="wa_weekly_digest"
                            setting="web_analytics_weekly_digest_project_enabled"
                            isTeamDisabled={(teamId) =>
                                !user?.notification_settings.web_analytics_weekly_digest_project_enabled?.[teamId]
                            }
                            onToggleTeam={updateWAWeeklyDigestForTeam}
                            onToggleAllTeams={updateWAWeeklyDigestForAllTeams}
                        />
                    </>
                )}
            </NotificationCard>
        ),
        [NotificationBlock.DataCatalogWeeklyDigest]: (
            <NotificationCard lemonClassName="border rounded p-4">
                <SimpleSwitch
                    setting="data_catalog_weekly_digest"
                    label="Data catalog weekly digest"
                    description="Get a weekly summary of the metrics, relationships, and certifications waiting for review in your projects"
                    dataAttr="data_catalog_weekly_digest_enabled"
                />
            </NotificationCard>
        ),
        [NotificationBlock.CommentMentions]: (
            <NotificationCard lemonClassName="border rounded p-4">
                <SimpleSwitch
                    setting="discussions_mentioned"
                    label="Comment mentions"
                    description="Get notified when someone mentions you in a discussion on any project"
                    dataAttr="discussions_mentioned_enabled"
                />
            </NotificationCard>
        ),
        [NotificationBlock.Approvals]: (
            <NotificationCard lemonClassName="border rounded p-4 space-y-3">
                {todayRailNav ? (
                    <QuillApprovalsHeading />
                ) : (
                    <div className="flex items-center gap-1 font-semibold">
                        <span>Approvals</span>
                        <Tooltip title={APPROVALS_TOOLTIP}>
                            <IconQuestion className="text-secondary text-base" />
                        </Tooltip>
                    </div>
                )}
                <SimpleSwitch
                    setting="approval_requested"
                    label="Approval requests"
                    description="Get an email when a change needs your approval"
                    dataAttr="approval_requested_enabled"
                />
                <SimpleSwitch
                    setting="approval_resolved"
                    label="Change request updates"
                    description="Get an email when your change request is approved, declined, expires, or goes live"
                    dataAttr="approval_resolved_enabled"
                />
            </NotificationCard>
        ),
        [NotificationBlock.ApiKeyExposure]: (
            <NotificationCard lemonClassName="border rounded p-4">
                <SimpleSwitch
                    setting="project_api_key_exposed"
                    label="Private API key exposure"
                    description="Get notified when private API keys are publicly exposed"
                    dataAttr="project_api_key_exposure_enabled"
                />
            </NotificationCard>
        ),
        [NotificationBlock.AiEvaluationDisabled]: (
            <NotificationCard lemonClassName="border rounded p-4">
                <SimpleSwitch
                    setting="ai_evaluation_disabled"
                    label="Disabled AI evaluations"
                    description="Get notified when an AI observability evaluation stops because of an error"
                    dataAttr="ai_evaluation_disabled_enabled"
                />
            </NotificationCard>
        ),
        [NotificationBlock.WorkflowSuggestions]: (
            <NotificationCard lemonClassName="border rounded p-4">
                <SimpleSwitch
                    setting="workflow_suggestions"
                    label="Workflow suggestions"
                    description="Get an email when PostHog suggests a change to a workflow you set up"
                    dataAttr="workflow_suggestions_enabled"
                />
            </NotificationCard>
        ),
        [NotificationBlock.MaterializedViewSync]: (
            <NotificationCard lemonClassName="border rounded p-4 space-y-3">
                <SimpleSwitch
                    setting="materialized_view_sync_failed"
                    label="Materialized view sync failures"
                    description="Get notified when a materialized view fails to sync"
                    dataAttr="materialized_view_sync_failed_enabled"
                />
                <MatviewFailureEmailOptions />
            </NotificationCard>
        ),
    }

    const visibleBlocks = NOTIFICATION_BLOCK_ORDER.filter(
        (block) => block !== NotificationBlock.Approvals || hasAvailableFeature(AvailableFeature.APPROVALS)
    )
    const highlightedBlock = highlight && visibleBlocks.includes(highlight) ? highlight : null
    const highlightRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (dataLoaded && highlightRef.current) {
            highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
    }, [dataLoaded, highlightedBlock])

    if (todayRailNav) {
        return (
            <QuillUpdateEmailPreferences
                blocks={blocks}
                visibleBlocks={visibleBlocks}
                highlightedBlock={highlightedBlock}
                highlightRef={highlightRef}
            />
        )
    }

    return (
        <div className="space-y-3">
            {visibleBlocks.map((key) => (
                <div
                    key={key}
                    ref={key === highlightedBlock ? highlightRef : undefined}
                    className={key === highlightedBlock ? 'ring-2 ring-accent-primary rounded-lg' : undefined}
                >
                    {blocks[key]}
                </div>
            ))}
        </div>
    )
}

const MatviewFailureEmailOptions = (): JSX.Element | null => {
    const { user } = useValues(userLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!user?.notification_settings?.materialized_view_sync_failed) {
        return null
    }

    return (
        <div className={todayRailNav ? 'flex flex-col gap-3 ps-9' : 'pl-6 space-y-3'}>
            <SimpleSwitch
                setting="materialized_view_sync_failed_daily"
                label="Daily digest"
                description="One email a day summarizing failing views."
                dataAttr="materialized_view_sync_failed_daily"
            />
            <SimpleSwitch
                setting="materialized_view_sync_failed_immediate"
                label="Right away"
                description="An email when a view starts failing. While it keeps failing, only the daily digest lists it."
                dataAttr="materialized_view_sync_failed_immediate"
            />
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

    const enforced = lockedValueFor(user?.notification_locks, setting)
    const value = enforced ?? user?.notification_settings?.[setting]
    const defaultValue = NOTIFICATION_DEFAULTS[setting]
    let checked: boolean = typeof value === 'boolean' ? value : typeof defaultValue === 'boolean' ? defaultValue : false
    if (inverse) {
        checked = !checked
    }

    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (newChecked: boolean): void => {
        user?.notification_settings &&
            updateUser({
                notification_settings: {
                    ...user?.notification_settings,
                    [setting]: inverse ? !newChecked : newChecked,
                },
            })
    }

    if (todayRailNav) {
        return (
            <QuillNotificationSwitch
                dataAttr={dataAttr}
                label={label}
                description={description}
                checked={checked}
                onCheckedChange={handleChange}
                disabledReason={lockedDisabledReason(enforced, userLoading)}
                lockedByAdmin={enforced !== null}
            />
        )
    }

    return (
        <div className="space-y-2">
            <LemonSwitch
                data-attr={dataAttr}
                onChange={handleChange}
                checked={checked}
                disabledReason={lockedDisabledReason(enforced, userLoading)}
                label={
                    <span className="flex items-center gap-2">
                        {label}
                        {enforced !== null && <LemonTag type="highlight">Set by your admin</LemonTag>}
                    </span>
                }
            />
            <span className="text-muted text-sm">{description}</span>
        </div>
    )
}
