import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import React, { useState } from 'react'
import { sceneConfigurations } from 'scenes/scenes'
import { PushpinOutlined } from '@ant-design/icons'
import { ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import {
    IconArrowDropDown,
    IconBarChart,
    IconCohort,
    IconComment,
    IconExtension,
    IconFlag,
    IconGauge,
    IconGroupedEvents,
    IconPerson,
    IconPlus,
    IconRecording,
    IconSettings,
    IconTools,
} from 'lib/components/icons'
import { LemonButton, LemonButtonProps, LemonButtonWithSideAction, SideAction } from 'lib/components/LemonButton'
import { LemonSpacer } from 'lib/components/LemonRow'
import { Lettermark } from 'lib/components/Lettermark/Lettermark'
import { dashboardsModel } from '~/models/dashboardsModel'
import { organizationLogic } from '~/scenes/organizationLogic'
import { canViewPlugins } from '~/scenes/plugins/access'
import { sceneLogic } from '~/scenes/sceneLogic'
import { Scene } from '~/scenes/sceneTypes'
import { teamLogic } from '~/scenes/teamLogic'
import { urls } from '~/scenes/urls'
import { InsightType } from '~/types'
import './SideBar.scss'
import { navigationLogic } from '../navigationLogic'
import { ToolbarModal } from '~/layout/ToolbarModal/ToolbarModal'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { groupsModel } from '~/models/groupsModel'

function ProjectSwitcherInternal(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { isProjectSwitcherShown } = useValues(navigationLogic)
    const { toggleProjectSwitcher, hideProjectSwitcher } = useActions(navigationLogic)

    return (
        <div className="ProjectSwitcher">
            <div className="SideBar__heading">Project</div>
            <LemonButton
                icon={<Lettermark name={currentOrganization?.name} />}
                fullWidth
                type="stealth"
                onClick={toggleProjectSwitcher}
                popup={{
                    visible: isProjectSwitcherShown,
                    onClickOutside: hideProjectSwitcher,
                    sameWidth: true,
                    overlay: <ProjectSwitcherOverlay />,
                    actionable: true,
                }}
            >
                <strong>{currentTeam ? currentTeam.name : <i>Choose project</i>}</strong>
            </LemonButton>
        </div>
    )
}
interface PageButtonProps extends Pick<LemonButtonProps, 'icon' | 'onClick' | 'popup' | 'to'> {
    /** Used for highlighting the active scene. `identifier` of type number means dashboard ID instead of scene. */
    identifier: string | number
    sideAction?: Omit<SideAction, 'type'> & { identifier?: string }
    title?: string
}

function PageButton({ title, sideAction, identifier, ...buttonProps }: PageButtonProps): JSX.Element {
    const { aliasedActiveScene, activeScene } = useValues(sceneLogic)
    const { lastDashboardId } = useValues(dashboardsModel)

    const isActiveSide: boolean = sideAction?.identifier === aliasedActiveScene
    const isActive: boolean =
        isActiveSide ||
        (typeof identifier === 'string'
            ? identifier === aliasedActiveScene
            : activeScene === Scene.Dashboard && identifier === lastDashboardId)

    return sideAction ? (
        <LemonButtonWithSideAction
            fullWidth
            type={isActive ? 'highlighted' : 'stealth'}
            sideAction={{
                ...sideAction,
                type: isActiveSide ? 'highlighted' : isActive ? undefined : 'stealth',
                'data-attr': sideAction.identifier ? `menu-item-${sideAction.identifier.toLowerCase()}` : undefined,
            }}
            data-attr={`menu-item-${identifier.toString().toLowerCase()}`}
            {...buttonProps}
        >
            {title || sceneConfigurations[identifier].name}
        </LemonButtonWithSideAction>
    ) : (
        <LemonButton
            fullWidth
            type={isActive ? 'highlighted' : 'stealth'}
            data-attr={`menu-item-${identifier.toString().toLowerCase()}`}
            {...buttonProps}
        >
            {title || sceneConfigurations[identifier].name}
        </LemonButton>
    )
}

function Pages(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { showToolbarModal } = useActions(navigationLogic)
    const { pinnedDashboards } = useValues(dashboardsModel)
    const { featureFlags } = useValues(featureFlagLogic)
    const { showGroupsOptions } = useValues(groupsModel)

    const [arePinnedDashboardsShown, setArePinnedDashboardsShown] = useState(false)

    return (
        <div className="Pages">
            {currentOrganization?.setup.is_active && (
                <>
                    <PageButton
                        title="Setup"
                        icon={<IconSettings />}
                        identifier={Scene.OnboardingSetup}
                        to={urls.onboardingSetup()}
                    />
                    <LemonSpacer />
                </>
            )}
            <PageButton
                icon={<IconGauge />}
                identifier={Scene.Dashboards}
                to={urls.dashboards()}
                sideAction={{
                    icon: <IconArrowDropDown />,
                    identifier: 'pinned-dashboards',
                    tooltip: 'Pinned dashboards',
                    onClick: () => setArePinnedDashboardsShown((state) => !state),
                    popup: {
                        visible: arePinnedDashboardsShown,
                        onClickOutside: () => setArePinnedDashboardsShown(false),
                        overlay: (
                            <div className="SideBar__pinned-dashboards">
                                <h5>Pinned dashboards</h5>
                                <LemonSpacer />
                                {pinnedDashboards.length > 0 ? (
                                    pinnedDashboards.map((dashboard) => (
                                        <PageButton
                                            key={dashboard.id}
                                            title={dashboard.name}
                                            identifier={dashboard.id}
                                            onClick={() => setArePinnedDashboardsShown(false)}
                                            to={urls.dashboard(dashboard.id)}
                                        />
                                    ))
                                ) : (
                                    <div className="text-muted text-center" style={{ maxWidth: 220 }}>
                                        <PushpinOutlined style={{ marginRight: 4 }} /> Pinned dashboards will show here.{' '}
                                        <Link onClick={() => setArePinnedDashboardsShown(false)} to={urls.dashboards()}>
                                            Go to dashboards
                                        </Link>
                                        .
                                    </div>
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
                    to: urls.insightNew({ insight: InsightType.TRENDS }),
                    tooltip: 'New insight',
                    identifier: Scene.Insight,
                }}
            />
            <PageButton icon={<IconRecording />} identifier={Scene.SessionRecordings} to={urls.sessionRecordings()} />
            <PageButton icon={<IconFlag />} identifier={Scene.FeatureFlags} to={urls.featureFlags()} />
            {featureFlags[FEATURE_FLAGS.EXPERIMENTATION] && (
                <PageButton icon={<IconFlag />} identifier={Scene.Experiments} to={urls.experiments()} />
            )}
            <LemonSpacer />
            <PageButton icon={<IconGroupedEvents />} identifier={Scene.Events} to={urls.events()} />
            <PageButton
                icon={<IconPerson />}
                identifier={Scene.Persons}
                to={urls.persons()}
                title={`Persons${showGroupsOptions ? ' & groups' : ''}`}
            />
            <PageButton icon={<IconCohort />} identifier={Scene.Cohorts} to={urls.cohorts()} />
            <PageButton icon={<IconComment />} identifier={Scene.Annotations} to={urls.annotations()} />
            <LemonSpacer />
            {canViewPlugins(currentOrganization) && (
                <PageButton icon={<IconExtension />} identifier={Scene.Plugins} to={urls.plugins()} />
            )}
            <PageButton title="Toolbar" icon={<IconTools />} identifier="Toolbar" onClick={showToolbarModal} />
            <PageButton icon={<IconSettings />} identifier={Scene.ProjectSettings} to={urls.projectSettings()} />
        </div>
    )
}

export function SideBar({ children }: { children: React.ReactNode }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { isSideBarShown, isToolbarModalShown } = useValues(navigationLogic)
    const { hideSideBar, hideToolbarModal } = useActions(navigationLogic)

    return (
        <div className={clsx('SideBar', 'SideBar__layout', !isSideBarShown && 'SideBar--hidden')}>
            <div className="SideBar__slider">
                <div className="SideBar__content">
                    <ProjectSwitcherInternal />
                    {currentTeam && (
                        <>
                            <LemonSpacer />
                            <Pages />
                        </>
                    )}
                </div>
            </div>
            <div className="SideBar__overlay" onClick={hideSideBar} />
            {children}
            <ToolbarModal visible={isToolbarModalShown} onCancel={hideToolbarModal} />
        </div>
    )
}
