import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonSwitch, Tooltip } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel, TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { QuillSettingSwitch } from '../components/QuillSettingSwitch'
import { QuillActivityLogHelpText } from './QuillActivityLogHelpText'

// These settings are gated as a whole. The AUDIT_LOGS pay gate is declared on the
// `environment-activity-logs` section in SettingsMap, not on each component here.

const ORG_LEVEL_HELP =
    "When enabled, activity logs from organization-level changes (such as organization settings, domains, and members) will be included in this project's activity logs page, exports, and notifications subscriptions."

const NOTIFICATIONS_HELP =
    'You can filter by activity type, resource, and other properties to receive only the notifications you need.'

export function ActivityLogSettings(): JSX.Element {
    const { user } = useValues(userLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const effectiveRestriction = user?.is_impersonated ? null : restrictedReason
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <div>
                <Button
                    variant="primary"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.advancedActivityLogs()} />}
                    disabledReason={effectiveRestriction}
                >
                    Browse all activity logs
                </Button>
            </div>
        )
    }

    return (
        <div className="flex">
            <p>
                <LemonButton to={urls.advancedActivityLogs()} type="primary" disabledReason={effectiveRestriction}>
                    Browse all activity logs
                </LemonButton>
            </p>
        </div>
    )
}

export function ActivityLogOrgLevelSettings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportActivityLogSettingToggled } = useActions(eventUsageLogic)

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleToggle = (checked: boolean): void => {
        updateCurrentTeam({ receive_org_level_activity_logs: checked })
        reportActivityLogSettingToggled(checked)
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <QuillActivityLogHelpText
                    text="Include organization-level activity logs in this project."
                    help={ORG_LEVEL_HELP}
                />
                <QuillSettingSwitch
                    id="posthog-activity-log-org-level-switch"
                    label="Include organization-level activity"
                    checked={!!currentTeam?.receive_org_level_activity_logs}
                    onCheckedChange={handleToggle}
                    disabledReason={restrictionReason}
                />
            </div>
        )
    }

    return (
        <div>
            <p className="flex items-center gap-1">
                Include organization-level activity logs in this project.
                <Tooltip title={ORG_LEVEL_HELP}>
                    <IconInfo className="text-lg" />
                </Tooltip>
            </p>

            <LemonSwitch
                id="posthog-activity-log-org-level-switch"
                onChange={handleToggle}
                checked={!!currentTeam?.receive_org_level_activity_logs}
                disabledReason={restrictionReason || undefined}
                label="Include organization-level activity"
                bordered
            />
        </div>
    )
}

export function ActivityLogNotifications(): JSX.Element | null {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (restrictedReason) {
        return null
    }

    const linkedHogFunctions = (
        <LinkedHogFunctions
            type="internal_destination"
            subTemplateIds={['activity-log']}
            queryParams={{
                returnTo: urls.settings('environment-activity-logs', 'activity-log-notifications'),
            }}
        />
    )

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <QuillActivityLogHelpText
                    text="Create notifications to get notified of activity logs."
                    help={NOTIFICATIONS_HELP}
                />
                {linkedHogFunctions}
            </div>
        )
    }

    return (
        <div>
            <p className="flex items-center gap-1">
                Create notifications to get notified of activity logs.
                <Tooltip title={NOTIFICATIONS_HELP}>
                    <IconInfo className="text-lg" />
                </Tooltip>
            </p>

            {linkedHogFunctions}
        </div>
    )
}
