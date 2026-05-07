import { useActions, useValues } from 'kea'

import { IconInfo, IconNotification } from '@posthog/icons'
import { LemonSegmentedButton, LemonTabs, Link, Tooltip } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType, AvailableFeature } from '~/types'

import { AdvancedActivityLogFiltersPanel } from './AdvancedActivityLogFiltersPanel'
import { AdvancedActivityLogsList } from './AdvancedActivityLogsList'
import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'
import type { ActivityLogsScope } from './advancedActivityLogsLogic'
import { ExportsList } from './ExportsList'

export const scene: SceneExport = {
    component: AdvancedActivityLogsScene,
    logic: advancedActivityLogsLogic,
}

export function AdvancedActivityLogsScene(): JSX.Element | null {
    const { activeTab, scope, canViewOrganizationScope } = useValues(advancedActivityLogsLogic)
    const { setActiveTab, setScope } = useActions(advancedActivityLogsLogic)
    const { currentTeam } = useValues(teamLogic)

    const hasAccess = userHasAccess(AccessControlResourceType.ActivityLog, AccessControlLevel.Viewer)
    const includesOrgLevelLogs = currentTeam?.receive_org_level_activity_logs
    const inOrganizationScope = scope === 'organization'

    const tabs = inOrganizationScope
        ? [
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
          ]
        : [
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
              {
                  key: 'exports',
                  label: 'Exports',
                  content: <ExportsList />,
              },
          ]

    if (!hasAccess) {
        return (
            <SceneContent>
                <AccessDenied object="activity logs" />
            </SceneContent>
        )
    }

    const scopeStatusLabel = inOrganizationScope
        ? 'Showing activity across the entire organization.'
        : includesOrgLevelLogs
          ? 'This view includes activity from both this project and organization-level changes (such as organization settings, domains, and members).'
          : 'This view only includes activity from this project. Organization-level changes are not shown.'

    return (
        <SceneContent>
            <SceneTitleSection
                name="Activity logs"
                resourceType={{
                    type: 'team_activity',
                    forceIcon: <IconNotification />,
                }}
            />
            <PayGateMini feature={AvailableFeature.AUDIT_LOGS}>
                <LemonTabs
                    activeKey={inOrganizationScope ? 'logs' : activeTab}
                    onChange={(key) => setActiveTab(key as 'logs' | 'exports')}
                    tabs={tabs}
                    sceneInset
                    rightSlot={
                        <div className="flex items-center gap-3">
                            {canViewOrganizationScope && (
                                <Tooltip title="Switch between activity logs scoped to this project and activity logs across all projects in the organization. Organization scope is restricted to organization admins and owners.">
                                    <span>
                                        <LemonSegmentedButton
                                            size="small"
                                            value={scope}
                                            onChange={(value) => setScope(value as ActivityLogsScope)}
                                            options={[
                                                { value: 'project', label: 'Project' },
                                                { value: 'organization', label: 'Organization' },
                                            ]}
                                            data-attr="audit-logs-scope-toggle"
                                        />
                                    </span>
                                </Tooltip>
                            )}
                            <Tooltip
                                title={
                                    <>
                                        {scopeStatusLabel}
                                        {!inOrganizationScope && (
                                            <>
                                                <br />
                                                <Link
                                                    to={urls.settings(
                                                        'environment-activity-logs',
                                                        'activity-log-org-level-settings'
                                                    )}
                                                >
                                                    Change in settings
                                                </Link>
                                            </>
                                        )}
                                    </>
                                }
                            >
                                <span className="flex items-center gap-1 text-sm text-secondary whitespace-nowrap cursor-pointer">
                                    {inOrganizationScope
                                        ? 'Organization-wide logs'
                                        : includesOrgLevelLogs
                                          ? 'Project and organization logs'
                                          : 'Project logs only'}
                                    <IconInfo className="text-base" />
                                </span>
                            </Tooltip>
                        </div>
                    }
                />
            </PayGateMini>
        </SceneContent>
    )
}
