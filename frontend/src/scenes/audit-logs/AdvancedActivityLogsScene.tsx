import { useActions, useValues } from 'kea'

import { IconInfo, IconNotification } from '@posthog/icons'
import { LemonSegmentedButton, LemonTabs, Link, Tooltip } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType, AvailableFeature } from '~/types'

import { AdvancedActivityLogFiltersPanel } from './AdvancedActivityLogFiltersPanel'
import { AdvancedActivityLogsList } from './AdvancedActivityLogsList'
import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'
import type { ActivityLogsView } from './advancedActivityLogsLogic'
import { ExportsList } from './ExportsList'

export const scene: SceneExport = {
    component: AdvancedActivityLogsScene,
    logic: advancedActivityLogsLogic,
}

export function AdvancedActivityLogsScene(): JSX.Element | null {
    const { activeTab, view, canViewOrganization, isOrganizationView } = useValues(advancedActivityLogsLogic)
    const { setActiveTab, setView } = useActions(advancedActivityLogsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { user } = useValues(userLogic)

    const hasAccess = userHasAccess(AccessControlResourceType.ActivityLog, AccessControlLevel.Viewer)
    const includesOrgLevelLogs = currentTeam?.receive_org_level_activity_logs

    const tabs = [
        {
            key: 'logs',
            label: 'Logs',
            content: (
                <div className="space-y-4">
                    <AdvancedActivityLogFiltersPanel />
                    <AdvancedActivityLogsList />
                </div>
            ),
        },
        // Exports is project-scoped only — org view doesn't yet have an export path
        ...(isOrganizationView
            ? []
            : [
                  {
                      key: 'exports',
                      label: 'Exports',
                      content: <ExportsList />,
                  },
              ]),
    ]

    if (!hasAccess) {
        return (
            <SceneContent>
                <AccessDenied object="activity logs" />
            </SceneContent>
        )
    }

    const projectViewTooltip = (
        <>
            {includesOrgLevelLogs
                ? 'This project view also includes organization-level changes (such as organization settings, domains, and members).'
                : 'This project view only shows activity from this project. Organization-level changes are not shown.'}
            <br />
            <Link to={urls.settings('environment-activity-logs', 'activity-log-org-level-settings')}>
                Change in settings
            </Link>
        </>
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name="Activity logs"
                resourceType={{
                    type: 'team_activity',
                    forceIcon: <IconNotification />,
                }}
            />
            <PayGateMini feature={AvailableFeature.AUDIT_LOGS} overrideShouldShowGate={user?.is_impersonated}>
                <LemonTabs
                    activeKey={isOrganizationView ? 'logs' : activeTab}
                    onChange={(key) => setActiveTab(key as 'logs' | 'exports')}
                    tabs={tabs}
                    sceneInset
                    rightSlot={
                        <div className="flex items-center gap-3">
                            {canViewOrganization ? (
                                <LemonSegmentedButton
                                    size="small"
                                    value={view}
                                    onChange={(value) => setView(value as ActivityLogsView)}
                                    options={[
                                        {
                                            value: 'project',
                                            label: (
                                                <span className="flex items-center gap-1">
                                                    Project
                                                    <IconInfo className="text-base" />
                                                </span>
                                            ),
                                            tooltip: projectViewTooltip,
                                        },
                                        {
                                            value: 'organization',
                                            label: 'Organization',
                                            tooltip: 'Activity across all projects in the organization.',
                                        },
                                    ]}
                                    data-attr="audit-logs-view-toggle"
                                />
                            ) : (
                                // No toggle for non-admins — keep the contextual indicator inline.
                                <Tooltip title={projectViewTooltip}>
                                    <span className="flex items-center gap-1 text-sm text-secondary whitespace-nowrap cursor-pointer">
                                        {includesOrgLevelLogs ? 'Project and organization logs' : 'Project logs only'}
                                        <IconInfo className="text-base" />
                                    </span>
                                </Tooltip>
                            )}
                        </div>
                    }
                />
            </PayGateMini>
        </SceneContent>
    )
}
