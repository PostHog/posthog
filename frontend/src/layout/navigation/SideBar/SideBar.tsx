import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { useState } from 'react'
import { ProjectName, ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import {
    IconApps,
    IconBarChart,
    IconCohort,
    IconDatabase,
    IconExperiment,
    IconFlag,
    IconGauge,
    IconLive,
    IconMessages,
    IconOpenInApp,
    IconPinOutline,
    IconPipeline,
    IconPlus,
    IconRecording,
    IconRocketLaunch,
    IconSettings,
    IconSurveys,
    IconTools,
    IconUnverifiedEvent,
    IconWeb,
} from 'lib/lemon-ui/icons'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { dashboardsModel } from '~/models/dashboardsModel'
import { organizationLogic } from '~/scenes/organizationLogic'
import { canViewPlugins } from '~/scenes/plugins/access'
import { Scene } from '~/scenes/sceneTypes'
import { isAuthenticatedTeam, teamLogic } from '~/scenes/teamLogic'
import { urls } from '~/scenes/urls'
import { AvailableFeature } from '~/types'
import './SideBar.scss'
import { navigationLogic } from '../navigationLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SideBarApps } from '~/layout/navigation/SideBar/SideBarApps'
import { PageButton } from '~/layout/navigation/SideBar/PageButton'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { authorizedUrlListLogic, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { DebugNotice } from 'lib/components/DebugNotice'
import { NotebookPopover } from 'scenes/notebooks/NotebookPanel/NotebookPopover'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { IconNotebook } from 'scenes/notebooks/IconNotebook'
import { ActivationSidebar } from 'lib/components/ActivationSidebar/ActivationSidebar'

function Pages(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { hideSideBarMobile, toggleProjectSwitcher, hideProjectSwitcher } = useActions(navigationLogic)
    const { isProjectSwitcherShown } = useValues(navigationLogic)
    const { pinnedDashboards } = useValues(dashboardsModel)
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
                    <FlaggedFeature flag="notebooks">
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
                    </FlaggedFeature>
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
                    <FlaggedFeature flag={FEATURE_FLAGS.WEB_ANALYTICS}>
                        <PageButton
                            icon={<IconWeb />}
                            identifier={Scene.WebAnalytics}
                            to={urls.webAnalytics()}
                            highlight="beta"
                        />
                    </FlaggedFeature>
                    <PageButton icon={<IconRecording />} identifier={Scene.Replay} to={urls.replay()} />

                    <div className="SideBar__heading">Feature Management</div>

                    <PageButton icon={<IconFlag />} identifier={Scene.FeatureFlags} to={urls.featureFlags()} />

                    {(hasAvailableFeature(AvailableFeature.EXPERIMENTATION) ||
                        !preflight?.instance_preferences?.disable_paid_fs) && (
                        <PageButton icon={<IconExperiment />} identifier={Scene.Experiments} to={urls.experiments()} />
                    )}
                    <PageButton
                        icon={<IconSurveys />}
                        identifier={Scene.Surveys}
                        title={'Surveys'}
                        to={urls.surveys()}
                        highlight="new"
                    />
                    <PageButton
                        icon={<IconRocketLaunch />}
                        identifier={Scene.EarlyAccessFeatures}
                        title={'Early access features'}
                        to={urls.earlyAccessFeatures()}
                    />
                    <div className="SideBar__heading">Data</div>

                    <PageButton
                        icon={<IconLive />}
                        identifier={Scene.Events}
                        to={urls.events()}
                        title={'Event explorer'}
                    />
                    <PageButton
                        icon={<IconUnverifiedEvent />}
                        identifier={Scene.DataManagement}
                        to={urls.eventDefinitions()}
                    />
                    <PageButton
                        icon={<IconCohort />}
                        identifier={Scene.PersonsManagement}
                        to={urls.persons()}
                        title="People"
                    />
                    <FlaggedFeature flag={FEATURE_FLAGS.PIPELINE_UI}>
                        <PageButton icon={<IconPipeline />} identifier={Scene.Pipeline} to={urls.pipeline()} />
                    </FlaggedFeature>
                    <FlaggedFeature flag={FEATURE_FLAGS.DATA_WAREHOUSE}>
                        <PageButton
                            icon={<IconDatabase />}
                            identifier={Scene.DataWarehouse}
                            title={'Data warehouse'}
                            to={urls.dataWarehouse()}
                            highlight="beta"
                        />
                    </FlaggedFeature>
                    {canViewPlugins(currentOrganization) || Object.keys(frontendApps).length > 0 ? (
                        <>
                            <div className="SideBar__heading">Apps</div>
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
                    <FlaggedFeature flag={FEATURE_FLAGS.FEEDBACK_SCENE}>
                        <PageButton icon={<IconMessages />} identifier={Scene.Feedback} to={urls.feedback()} />
                    </FlaggedFeature>
                    <div className="SideBar__heading">Configuration</div>

                    <PageButton
                        icon={<IconTools />}
                        identifier={Scene.ToolbarLaunch}
                        to={urls.toolbarLaunch()}
                        sideAction={{
                            identifier: 'toolbar-launch',
                            tooltip: 'Launch toolbar',
                            onClick: () => setIsToolbarLaunchShown((state) => !state),
                            dropdown: {
                                visible: isToolbarLaunchShown,
                                onClickOutside: () => setIsToolbarLaunchShown(false),
                                onClickInside: hideSideBarMobile,
                                overlay: <AppUrls setIsToolbarLaunchShown={setIsToolbarLaunchShown} />,
                            },
                        }}
                    />
                    <PageButton icon={<IconSettings />} identifier={Scene.Settings} to={urls.settings('project')} />
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

function AppUrls({ setIsToolbarLaunchShown }: { setIsToolbarLaunchShown: (state: boolean) => void }): JSX.Element {
    const { authorizedUrls, launchUrl, suggestionsLoading } = useValues(
        authorizedUrlListLogic({ type: AuthorizedUrlListType.TOOLBAR_URLS, actionId: null })
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
                            {appUrl}
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
