import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { useState } from 'react'
import { ProjectName, ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import {
    IconApps,
    IconBarChart,
    IconCoffee,
    IconCohort,
    IconComment,
    IconExperiment,
    IconFlag,
    IconGauge,
    IconLive,
    IconOpenInApp,
    IconPerson,
    IconPinOutline,
    IconPlus,
    IconRecording,
    IconSettings,
    IconTools,
    IconUnverifiedEvent,
} from 'lib/lemon-ui/icons'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
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
import { userLogic } from 'scenes/userLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SideBarApps } from '~/layout/navigation/SideBar/SideBarApps'
import { PageButton } from '~/layout/navigation/SideBar/PageButton'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { AuthorizedUrlListType, authorizedUrlListLogic } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import Typography from 'antd/lib/typography'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { DebugNotice } from 'lib/components/DebugNotice'
import ActivationSidebar from 'lib/components/ActivationSidebar/ActivationSidebar'

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
    const [isToolbarLaunchShown, setIsToolbarLaunchShown] = useState(false)

    return (
        <ul>
            <div className="SideBar__heading">Project</div>
            <PageButton
                title={
                    currentTeam?.name ? (
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
                            onClick: () => setArePinnedDashboardsShown((state) => !state),
                            popup: {
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
                            icon={<IconCoffee />}
                            identifier={Scene.WebPerformance}
                            to={urls.webPerformance()}
                        />
                    )}
                    <div className="SideBar__heading">Data</div>

                    <PageButton
                        icon={<IconLive />}
                        identifier={Scene.Events}
                        to={urls.events()}
                        title={
                            featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_LIVE_EVENTS] ? 'Event Explorer' : 'Live Events'
                        }
                    />
                    <PageButton
                        icon={<IconUnverifiedEvent />}
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

                    <PageButton
                        icon={<IconTools />}
                        identifier={Scene.ToolbarLaunch}
                        to={urls.toolbarLaunch()}
                        sideAction={{
                            identifier: 'toolbar-launch',
                            tooltip: 'Launch toolbar',
                            onClick: () => setIsToolbarLaunchShown((state) => !state),
                            popup: {
                                visible: isToolbarLaunchShown,
                                onClickOutside: () => setIsToolbarLaunchShown(false),
                                onClickInside: hideSideBarMobile,
                                overlay: <AppUrls setIsToolbarLaunchShown={setIsToolbarLaunchShown} />,
                            },
                        }}
                    />
                    <PageButton
                        icon={<IconSettings />}
                        identifier={Scene.ProjectSettings}
                        to={urls.projectSettings()}
                    />
                </>
            )}
        </ul>
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
                    <DebugNotice />
                </div>
            </div>
            <div className="SideBar__overlay" onClick={hideSideBarMobile} />
            {children}
            <ActivationSidebar />
        </div>
    )
}

function AppUrls({ setIsToolbarLaunchShown }: { setIsToolbarLaunchShown: (state: boolean) => void }): JSX.Element {
    const { authorizedUrls, launchUrl, suggestionsLoading } = useValues(
        authorizedUrlListLogic({ type: AuthorizedUrlListType.TOOLBAR_URLS })
    )
    return (
        <div className="SideBar__side-actions" data-attr="sidebar-launch-toolbar">
            <h5>TOOLBAR URLS</h5>
            <LemonDivider />
            {suggestionsLoading ? (
                <Spinner />
            ) : (
                <>
                    {authorizedUrls.map((appUrl, index) => (
                        <LemonButton
                            className="LaunchToolbarButton"
                            status="stealth"
                            fullWidth
                            key={index}
                            onClick={() => setIsToolbarLaunchShown(false)}
                            to={launchUrl(appUrl)}
                            targetBlank
                            sideIcon={
                                <Tooltip title="Launch toolbar">
                                    <IconOpenInApp />
                                </Tooltip>
                            }
                        >
                            <Typography.Text ellipsis={true} title={appUrl}>
                                {appUrl}
                            </Typography.Text>
                        </LemonButton>
                    ))}
                    <LemonButton
                        status="stealth"
                        data-attr="sidebar-launch-toolbar-add-new-url"
                        fullWidth
                        to={`${urls.toolbarLaunch()}?addNew=true`}
                        onClick={() => setIsToolbarLaunchShown(false)}
                    >
                        Add toolbar URL
                    </LemonButton>
                </>
            )}
        </div>
    )
}
