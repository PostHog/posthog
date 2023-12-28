import './SideBar.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ActivationSidebar } from 'lib/components/ActivationSidebar/ActivationSidebar'
import { DebugNotice } from 'lib/components/DebugNotice'
import { IconApps, IconBarChart, IconGauge, IconPinOutline, IconPlus } from 'lib/lemon-ui/icons'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { Link } from 'lib/lemon-ui/Link'
import { useState } from 'react'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { IconNotebook } from 'scenes/notebooks/IconNotebook'
import { NotebookPopover } from 'scenes/notebooks/NotebookPanel/NotebookPopover'

import { ProjectName, ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import { PageButton } from '~/layout/navigation/SideBar/PageButton'
import { SideBarApps } from '~/layout/navigation/SideBar/SideBarApps'
import { dashboardsModel } from '~/models/dashboardsModel'
import { organizationLogic } from '~/scenes/organizationLogic'
import { canViewPlugins } from '~/scenes/plugins/access'
import { Scene } from '~/scenes/sceneTypes'
import { isAuthenticatedTeam, teamLogic } from '~/scenes/teamLogic'
import { urls } from '~/scenes/urls'

import { navigationLogic } from '../navigationLogic'

function Pages(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { hideSideBarMobile, toggleProjectSwitcher, hideProjectSwitcher } = useActions(navigationLogic)
    const { isProjectSwitcherShown } = useValues(navigationLogic)
    const { pinnedDashboards } = useValues(dashboardsModel)
    const { currentTeam } = useValues(teamLogic)
    const { frontendApps } = useValues(frontendAppsLogic)

    const [arePinnedDashboardsShown, setArePinnedDashboardsShown] = useState(false)

    return (
        <ul>
            <PageButton
                title={
                    isAuthenticatedTeam(currentTeam) ? (
                        <>
                            <span>
                                <ProjectName team={currentTeam} />
                            </span>
                        </>
                    ) : (
                        'Choose project'
                    )
                }
                icon={<Lettermark name={currentOrganization?.name} />}
                identifier={Scene.ProjectHomepage}
                to={urls.projectHomepage()}
                sideAction={{
                    'aria-label': 'switch project',
                    onClick: () => toggleProjectSwitcher(),
                    dropdown: {
                        visible: isProjectSwitcherShown,
                        onClickOutside: hideProjectSwitcher,
                        overlay: <ProjectSwitcherOverlay onClickInside={hideProjectSwitcher} />,
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
                            onClick: () => setArePinnedDashboardsShown((state) => !state),
                            dropdown: {
                                visible: arePinnedDashboardsShown,
                                onClickOutside: () => setArePinnedDashboardsShown(false),
                                onClickInside: hideSideBarMobile,
                                overlay: (
                                    <div className="SideBar__side-actions" data-attr="sidebar-pinned-dashboards">
                                        <h5>Pinned dashboards</h5>
                                        <LemonDivider />
                                        {pinnedDashboards.length > 0 ? (
                                            <ul>
                                                {pinnedDashboards.map((dashboard) => (
                                                    <PageButton
                                                        key={dashboard.id}
                                                        title={dashboard.name || <i>Untitled</i>}
                                                        identifier={dashboard.id}
                                                        onClick={() => setArePinnedDashboardsShown(false)}
                                                        to={urls.dashboard(dashboard.id)}
                                                    />
                                                ))}
                                            </ul>
                                        ) : (
                                            <>
                                                <div className="flex items-center gap-2">
                                                    <IconPinOutline className="text-2xl text-muted-alt" />
                                                    <div>
                                                        <Link
                                                            onClick={() => setArePinnedDashboardsShown(false)}
                                                            to={urls.dashboards()}
                                                        >
                                                            Pin some dashboards
                                                        </Link>
                                                        <br />
                                                        for them to show up here
                                                    </div>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                ),
                            },
                        }}
                    />
                    <PageButton
                        icon={<IconNotebook />}
                        identifier={Scene.Notebooks}
                        to={urls.notebooks()}
                        sideAction={{
                            icon: <IconPlus />,
                            to: urls.notebook('new'),
                            tooltip: 'New notebook',
                            identifier: Scene.Notebook,
                            onClick: hideSideBarMobile,
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

                    {canViewPlugins(currentOrganization) || Object.keys(frontendApps).length > 0 ? (
                        <>
                            {canViewPlugins(currentOrganization) && (
                                <PageButton
                                    title="Browse apps"
                                    icon={<IconApps />}
                                    identifier={Scene.Apps}
                                    to={urls.projectApps()}
                                />
                            )}

                            {Object.keys(frontendApps).length > 0 && <SideBarApps />}
                        </>
                    ) : null}
                </>
            )}
        </ul>
    )
}

export function SideBar({ children }: { children: React.ReactNode }): JSX.Element {
    const { isSideBarShown } = useValues(navigationLogic)
    const { hideSideBarMobile } = useActions(navigationLogic)

    return (
        <div className={clsx('SideBar', !isSideBarShown && 'SideBar--hidden')}>
            <div className="SideBar__slider">
                <div className="SideBar__slider__content">
                    <Pages />
                    <DebugNotice />
                </div>
            </div>
            <div className="SideBar__overlay" onClick={hideSideBarMobile} />
            <NotebookPopover />
            <div className="SideBar__content">{children}</div>
            <ActivationSidebar />
        </div>
    )
}
