import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import React, { useEffect, useState } from 'react'
import { ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import {
    EventStackGearIcon,
    IconApps,
    IconBarChart,
    IconCohort,
    IconComment,
    IconExperiment,
    IconFlag,
    IconGauge,
    IconPerson,
    IconPin,
    IconPlus,
    IconRecording,
    IconSettings,
    IconTools,
    IconLive,
} from 'lib/components/icons'
import { LemonDivider } from 'lib/components/LemonDivider'
import { Lettermark } from 'lib/components/Lettermark/Lettermark'
import { dashboardsModel } from '~/models/dashboardsModel'
import { organizationLogic } from '~/scenes/organizationLogic'
import { canViewPlugins } from '~/scenes/plugins/access'
import { Scene } from '~/scenes/sceneTypes'
import { teamLogic } from '~/scenes/teamLogic'
import { urls } from '~/scenes/urls'
import { AvailableFeature } from '~/types'
import './SideBar.scss'
import { navigationLogic } from '../navigationLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { groupsModel } from '~/models/groupsModel'
import { CoffeeOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SideBarApps } from '~/layout/navigation/SideBar/SideBarApps'
import { PageButton } from '~/layout/navigation/SideBar/PageButton'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { LemonRow } from 'lib/components/LemonRow'

function Pages(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { hideSideBarMobile, toggleProjectSwitcher, hideProjectSwitcher } = useActions(navigationLogic)
    const { isProjectSwitcherShown } = useValues(navigationLogic)
    const { pinnedDashboards } = useValues(dashboardsModel)
    const { featureFlags } = useValues(featureFlagLogic)
    const { showGroupsOptions } = useValues(groupsModel)
    const { hasAvailableFeature } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { currentTeam } = useValues(teamLogic)
    const { frontendApps } = useValues(frontendAppsLogic)

    const [arePinnedDashboardsShown, setArePinnedDashboardsShown] = useState(false)

    useEffect(() => console.log('currentOrganization', currentOrganization), [currentOrganization])
    useEffect(() => console.log('hideSideBarMobile', hideSideBarMobile), [hideSideBarMobile])
    useEffect(() => console.log('toggleProjectSwitcher', toggleProjectSwitcher), [toggleProjectSwitcher])
    useEffect(() => console.log('hideProjectSwitcher', hideProjectSwitcher), [hideProjectSwitcher])
    useEffect(() => console.log('isProjectSwitcherShown', isProjectSwitcherShown), [isProjectSwitcherShown])
    useEffect(() => console.log('pinnedDashboards', pinnedDashboards), [pinnedDashboards])
    useEffect(() => console.log('featureFlags', featureFlags), [featureFlags])
    useEffect(() => console.log('showGroupsOptions', showGroupsOptions), [showGroupsOptions])
    useEffect(() => console.log('hasAvailableFeature', hasAvailableFeature), [hasAvailableFeature])
    useEffect(() => console.log('preflight', preflight), [preflight])
    useEffect(() => console.log('currentTeam', currentTeam), [currentTeam])
    useEffect(() => console.log('frontendApps', frontendApps), [frontendApps])
    useEffect(() => console.log('arePinnedDashboardsShown', arePinnedDashboardsShown), [arePinnedDashboardsShown])

    return (
        <div className="Pages">
            <div className="SideBar__heading">Project</div>
            <PageButton
                title={currentTeam?.name ?? 'Choose project'}
                icon={<Lettermark name={currentOrganization?.name} />}
                identifier={Scene.ProjectHomepage}
                to={urls.projectHomepage()}
                sideAction={{
                    onClick: () => toggleProjectSwitcher(),
                    popup: {
                        visible: isProjectSwitcherShown,
                        onClickOutside: hideProjectSwitcher,
                        overlay: <ProjectSwitcherOverlay />,
                        actionable: true,
                    },
                }}
            />
            {currentTeam && (
                <>
                    <LemonDivider />
                    <PageButton
                        icon={<IconGauge />}
                        identifier={Scene.Dashboards}
                        to={urls.dashboards()}
                        sideAction={{
                            identifier: 'pinned-dashboards',
                            tooltip: 'Pinned dashboards',
                            onClick: () => setArePinnedDashboardsShown(!arePinnedDashboardsShown),
                            popup: {
                                actionable: true,
                                visible: arePinnedDashboardsShown,
                                onClickOutside: () => setArePinnedDashboardsShown(false),
                                onClickInside: hideSideBarMobile,
                                overlay: (
                                    <div className="SideBar__pinned-dashboards">
                                        <h5>Pinned dashboards</h5>
                                        <LemonDivider />
                                        {pinnedDashboards.length > 0 ? (
                                            pinnedDashboards.map((dashboard) => (
                                                <PageButton
                                                    key={dashboard.id}
                                                    title={dashboard.name || <i>Untitled</i>}
                                                    identifier={dashboard.id}
                                                    onClick={() => setArePinnedDashboardsShown(false)}
                                                    to={urls.dashboard(dashboard.id)}
                                                />
                                            ))
                                        ) : (
                                            <LemonRow icon={<IconPin />} fullWidth>
                                                <span>
                                                    <Link
                                                        onClick={() => setArePinnedDashboardsShown(false)}
                                                        to={urls.dashboards()}
                                                    >
                                                        Pin some dashboards
                                                    </Link>
                                                    <br />
                                                    for them to show up here
                                                </span>
                                            </LemonRow>
                                        )}
                                    </div>
                                ),
                            },
                        }}
                    />
                    <PageButton
                        icon={<IconBarChart />}
                        identifier={Scene.SavedInsights}
                        to={urls.savedInsights()}
                        sideAction={{
                            icon: <IconPlus />,
                            to: urls.insightNew(),
                            tooltip: 'New insight',
                            identifier: Scene.Insight,
                            onClick: hideSideBarMobile,
                        }}
                    />
                    <PageButton
                        icon={<IconRecording />}
                        identifier={Scene.SessionRecordings}
                        to={urls.sessionRecordings()}
                    />
                    <PageButton icon={<IconFlag />} identifier={Scene.FeatureFlags} to={urls.featureFlags()} />
                    {(hasAvailableFeature(AvailableFeature.EXPERIMENTATION) ||
                        !preflight?.instance_preferences?.disable_paid_fs) && (
                        <PageButton icon={<IconExperiment />} identifier={Scene.Experiments} to={urls.experiments()} />
                    )}
                    {featureFlags[FEATURE_FLAGS.WEB_PERFORMANCE] && (
                        <PageButton
                            icon={<CoffeeOutlined />}
                            identifier={Scene.WebPerformance}
                            to={urls.webPerformance()}
                        />
                    )}
                    {featureFlags[FEATURE_FLAGS.FRONTEND_APPS] ? (
                        <div className="SideBar__heading">Data</div>
                    ) : (
                        <LemonDivider />
                    )}

                    <PageButton icon={<IconLive />} identifier={Scene.Events} to={urls.events()} />
                    <PageButton
                        icon={<EventStackGearIcon />}
                        identifier={Scene.DataManagement}
                        to={urls.eventDefinitions()}
                    />
                    <PageButton
                        icon={<IconPerson />}
                        identifier={Scene.Persons}
                        to={urls.persons()}
                        title={`Persons${showGroupsOptions ? ' & Groups' : ''}`}
                    />
                    <PageButton icon={<IconCohort />} identifier={Scene.Cohorts} to={urls.cohorts()} />
                    <PageButton icon={<IconComment />} identifier={Scene.Annotations} to={urls.annotations()} />
                    {featureFlags[FEATURE_FLAGS.FRONTEND_APPS] ? (
                        <>
                            {canViewPlugins(currentOrganization) || Object.keys(frontendApps).length > 0 ? (
                                <>
                                    <div className="SideBar__heading">Apps</div>
                                    {canViewPlugins(currentOrganization) && (
                                        <PageButton
                                            title="Browse Apps"
                                            icon={<IconApps />}
                                            identifier={Scene.Plugins}
                                            to={urls.projectApps()}
                                        />
                                    )}
                                    {Object.keys(frontendApps).length > 0 && <SideBarApps />}
                                </>
                            ) : null}
                            <div className="SideBar__heading">Configuration</div>
                        </>
                    ) : (
                        <>
                            <LemonDivider />
                            {canViewPlugins(currentOrganization) && (
                                <PageButton icon={<IconApps />} identifier={Scene.Plugins} to={urls.projectApps()} />
                            )}
                        </>
                    )}

                    <PageButton icon={<IconTools />} identifier={Scene.ToolbarLaunch} to={urls.toolbarLaunch()} />
                    <PageButton
                        icon={<IconSettings />}
                        identifier={Scene.ProjectSettings}
                        to={urls.projectSettings()}
                    />
                </>
            )}
        </div>
    )
}

export function SideBar({ children }: { children: React.ReactNode }): JSX.Element {
    const { isSideBarShown } = useValues(navigationLogic)
    const { hideSideBarMobile } = useActions(navigationLogic)

    return (
        <div className={clsx('SideBar', 'SideBar__layout', !isSideBarShown && 'SideBar--hidden')}>
            <div className="SideBar__slider">
                <div className="SideBar__content">
                    <Pages />
                </div>
            </div>
            <div className="SideBar__overlay" onClick={hideSideBarMobile} />
            {children}
        </div>
    )
}
