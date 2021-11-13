import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { useState } from 'react'
import { sceneConfigurations } from 'scenes/scenes'
import { ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcherOverlay'
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
} from '../../../lib/components/icons'
import {
    LemonButton,
    LemonButtonProps,
    LemonButtonWithSideAction,
    SideAction,
} from '../../../lib/components/LemonButton'
import { Lettermark } from '../../../lib/components/Lettermark/Lettermark'
import { dashboardsModel } from '../../../models/dashboardsModel'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { canViewPlugins } from '../../../scenes/plugins/access'
import { sceneLogic } from '../../../scenes/sceneLogic'
import { Scene } from '../../../scenes/sceneTypes'
import { teamLogic } from '../../../scenes/teamLogic'
import { urls } from '../../../scenes/urls'
import { InsightType } from '../../../types'
import { ToolbarModal } from '../../ToolbarModal/ToolbarModal'
import { lemonadeLogic } from '../lemonadeLogic'
import './SideBar.scss'

function SidebarProjectSwitcher(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { isProjectSwitcherShown } = useValues(lemonadeLogic)
    const { toggleProjectSwitcher, hideProjectSwitcher } = useActions(lemonadeLogic)

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
                <strong>{currentTeam?.name}</strong>
            </LemonButton>
        </div>
    )
}

function Spacer(): JSX.Element {
    return <div className="SideBar__spacer" />
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
    const { showToolbarModal } = useActions(lemonadeLogic)
    const { pinnedDashboards } = useValues(dashboardsModel)

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
                    <Spacer />
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
                                <Spacer />
                                {pinnedDashboards.map((dashboard) => (
                                    <PageButton
                                        key={dashboard.id}
                                        title={dashboard.name}
                                        identifier={dashboard.id}
                                        onClick={() => setArePinnedDashboardsShown(false)}
                                        to={urls.dashboard(dashboard.id)}
                                    />
                                ))}
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
                    to: urls.newInsight(InsightType.TRENDS),
                    tooltip: 'New insight',
                    identifier: Scene.Insights,
                }}
            />
            <PageButton icon={<IconRecording />} identifier={Scene.SessionRecordings} to={urls.sessionRecordings()} />
            <PageButton icon={<IconFlag />} identifier={Scene.FeatureFlags} to={urls.featureFlags()} />
            <Spacer />
            <PageButton icon={<IconGroupedEvents />} identifier={Scene.Events} to={urls.events()} />
            <PageButton icon={<IconPerson />} identifier={Scene.Persons} to={urls.persons()} />
            <PageButton icon={<IconCohort />} identifier={Scene.Cohorts} to={urls.cohorts()} />
            <PageButton icon={<IconComment />} identifier={Scene.Annotations} to={urls.annotations()} />
            <Spacer />
            {canViewPlugins(currentOrganization) && (
                <PageButton icon={<IconExtension />} identifier={Scene.Plugins} to={urls.plugins()} />
            )}
            <PageButton title="Toolbar" icon={<IconTools />} identifier="Toolbar" onClick={showToolbarModal} />
            <PageButton icon={<IconSettings />} identifier={Scene.ProjectSettings} to={urls.projectSettings()} />
        </div>
    )
}

export function SideBar({ children }: { children: React.ReactNode }): JSX.Element {
    const { isSideBarShown, isToolbarModalShown } = useValues(lemonadeLogic)
    const { hideSideBar, hideToolbarModal } = useActions(lemonadeLogic)

    return (
        <div className={clsx('SideBar', 'SideBar__layout', !isSideBarShown && 'SideBar--hidden')}>
            <div className="SideBar__slider">
                <div className="SideBar__content">
                    <SidebarProjectSwitcher />
                    <Spacer />
                    <Pages />
                </div>
            </div>
            <div className="SideBar__overlay" onClick={hideSideBar} />
            {children}
            <ToolbarModal visible={isToolbarModalShown} onCancel={hideToolbarModal} />
        </div>
    )
}
