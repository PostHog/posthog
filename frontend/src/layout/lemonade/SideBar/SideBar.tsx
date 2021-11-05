import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { useState } from 'react'
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
import { LemonRow } from '../../../lib/components/LemonRow'
import { Lettermark } from '../../../lib/components/Lettermark/Lettermark'
import { dashboardsModel } from '../../../models/dashboardsModel'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { canViewPlugins } from '../../../scenes/plugins/access'
import { sceneLogic } from '../../../scenes/sceneLogic'
import { Scene } from '../../../scenes/sceneTypes'
import { teamLogic } from '../../../scenes/teamLogic'
import { urls } from '../../../scenes/urls'
import { userLogic } from '../../../scenes/userLogic'
import { AvailableFeature, TeamBasicType, ViewType } from '../../../types'
import { ToolbarModal } from '../../ToolbarModal/ToolbarModal'
import { lemonadeLogic } from '../lemonadeLogic'
import './SideBar.scss'

function CurrentProjectButton(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { push } = useActions(router)
    const { hideProjectSwitcher } = useActions(lemonadeLogic)

    return (
        <LemonRow
            status="highlighted"
            sideIcon={
                <LemonButton
                    compact
                    onClick={() => {
                        hideProjectSwitcher()
                        push(urls.projectSettings())
                    }}
                    icon={<IconSettings />}
                />
            }
            fullWidth
        >
            <strong>{currentTeam?.name}</strong>
        </LemonRow>
    )
}

function OtherProjectButton({ team }: { team: TeamBasicType }): JSX.Element {
    const { updateCurrentTeam } = useActions(userLogic)
    const { hideProjectSwitcher } = useActions(lemonadeLogic)

    return (
        <LemonButtonWithSideAction
            onClick={() => {
                hideProjectSwitcher()
                updateCurrentTeam(team.id, '/')
            }}
            sideAction={{
                icon: <IconSettings />,
                tooltip: `Go to ${team.name} settings`,
                onClick: () => {
                    hideProjectSwitcher()
                    updateCurrentTeam(team.id, '/project/settings')
                },
            }}
            title={`Switch to project ${team.name}`}
            type="stealth"
            fullWidth
        >
            {team.name}
        </LemonButtonWithSideAction>
    )
}

export function ProjectSwitcher(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization, isProjectCreationForbidden } = useValues(organizationLogic)
    const { isProjectSwitcherShown } = useValues(lemonadeLogic)
    const { showCreateProjectModal, toggleProjectSwitcher, hideProjectSwitcher } = useActions(lemonadeLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)

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
                    overlay: (
                        <>
                            <CurrentProjectButton />
                            {currentOrganization?.teams &&
                                currentOrganization.teams
                                    .filter((team) => team.id !== currentTeam?.id)
                                    .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                                    .map((team) => <OtherProjectButton key={team.id} team={team} />)}

                            <LemonButton
                                icon={<IconPlus />}
                                fullWidth
                                disabled={isProjectCreationForbidden}
                                onClick={() => {
                                    hideProjectSwitcher()
                                    guardAvailableFeature(
                                        AvailableFeature.ORGANIZATIONS_PROJECTS,
                                        'multiple projects',
                                        'Projects allow you to separate data and configuration for different products or environments.',
                                        showCreateProjectModal
                                    )
                                }}
                            >
                                New project
                            </LemonButton>
                        </>
                    ),
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

interface PageButtonProps extends Pick<LemonButtonProps, 'title' | 'icon' | 'onClick' | 'popup' | 'to'> {
    /** Used for highlighting the active scene. `identifier` of type number means dashboard ID instead of scene. */
    identifier: string | number
    sideAction?: Omit<SideAction, 'type'> & { identifier?: string }
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
            sideAction={{ ...sideAction, type: isActiveSide ? 'highlighted' : isActive ? undefined : 'stealth' }}
            {...buttonProps}
        >
            {title}
        </LemonButtonWithSideAction>
    ) : (
        <LemonButton fullWidth type={isActive ? 'highlighted' : 'stealth'} {...buttonProps}>
            {title}
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
                        identifier="onboardingSetup"
                        to={urls.onboardingSetup()}
                    />
                    <Spacer />
                </>
            )}
            <PageButton
                title="Dashboards"
                icon={<IconGauge />}
                identifier="dashboards"
                to={urls.dashboards()}
                sideAction={{
                    icon: <IconArrowDropDown />,
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
                title="Insights"
                icon={<IconBarChart />}
                identifier="savedInsights"
                to={urls.savedInsights()}
                sideAction={{
                    icon: <IconPlus />,
                    to: urls.insightView(ViewType.TRENDS),
                    tooltip: 'New insight',
                    identifier: 'insights',
                }}
            />
            <PageButton
                title="Recordings"
                icon={<IconRecording />}
                identifier="sessionRecordings"
                to={urls.sessionRecordings()}
            />
            <PageButton title="Feature flags" icon={<IconFlag />} identifier="featureFlags" to={urls.featureFlags()} />
            <Spacer />
            <PageButton title="Events & actions" icon={<IconGroupedEvents />} identifier="events" to={urls.events()} />
            <PageButton title="Persons" icon={<IconPerson />} identifier="persons" to={urls.persons()} />
            <PageButton title="Cohorts" icon={<IconCohort />} identifier="cohorts" to={urls.cohorts()} />
            <PageButton title="Annotations" icon={<IconComment />} identifier="annotations" to={urls.annotations()} />
            <Spacer />
            {canViewPlugins(currentOrganization) && (
                <PageButton title="Plugins" icon={<IconExtension />} identifier="plugins" to={urls.plugins()} />
            )}
            <PageButton title="Toolbar" icon={<IconTools />} identifier="toolbar" onClick={showToolbarModal} />
            <PageButton
                title="Project settings"
                icon={<IconSettings />}
                identifier="projectSettings"
                to={urls.projectSettings()}
            />
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
                    <ProjectSwitcher />
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
