import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React from 'react'
import {
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
    LemonButtonWithPopup,
    LemonButtonWithSideAction,
    SideAction,
} from '../../../lib/components/LemonButton'
import { LemonRow } from '../../../lib/components/LemonRow'
import { Lettermark } from '../../../lib/components/Lettermark/Lettermark'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { canViewPlugins } from '../../../scenes/plugins/access'
import { sceneLogic } from '../../../scenes/sceneLogic'
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

    return (
        <LemonRow
            status="highlighted"
            sideIcon={<LemonButton compact onClick={() => push(urls.projectSettings())} icon={<IconSettings />} />}
            fullWidth
        >
            <strong>{currentTeam?.name}</strong>
        </LemonRow>
    )
}

function OtherProjectButton({ team }: { team: TeamBasicType }): JSX.Element {
    const { updateCurrentTeam } = useActions(userLogic)

    return (
        <LemonButtonWithSideAction
            onClick={() => updateCurrentTeam(team.id, '/')}
            sideAction={{
                icon: <IconSettings />,
                tooltip: `Go to ${team.name} settings`,
                onClick: () => updateCurrentTeam(team.id, '/project/settings'),
            }}
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
    const { showCreateProjectModal } = useActions(lemonadeLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)

    return (
        <div className="ProjectSwitcher">
            <div className="SideBar__heading">Project</div>
            <LemonButtonWithPopup
                icon={<Lettermark name={currentOrganization?.name} />}
                fullWidth
                type="stealth"
                overlay={
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
                            onClick={() =>
                                guardAvailableFeature(
                                    AvailableFeature.ORGANIZATIONS_PROJECTS,
                                    'multiple projects',
                                    'Projects allow you to separate data and configuration for different products or environments.',
                                    showCreateProjectModal
                                )
                            }
                        >
                            New project
                        </LemonButton>
                    </>
                }
            >
                <strong>{currentTeam?.name}</strong>
            </LemonButtonWithPopup>
        </div>
    )
}

function Spacer(): JSX.Element {
    return <div className="SideBar__spacer" />
}

interface PageButtonProps extends Pick<LemonButtonProps, 'title' | 'icon'> {
    identifier: string
    onClick: (() => void) | string
    sideAction?: Omit<SideAction, 'type'> & { identifier: string }
}

function PageButton({ title, icon, sideAction, identifier, onClick }: PageButtonProps): JSX.Element {
    const { aliasedActiveScene } = useValues(sceneLogic)

    const isActiveSide: boolean = sideAction?.identifier === aliasedActiveScene
    const isActive: boolean = isActiveSide || identifier === aliasedActiveScene

    return sideAction ? (
        <LemonButtonWithSideAction
            icon={icon}
            fullWidth
            type={isActive ? 'highlighted' : 'stealth'}
            onClick={onClick}
            sideAction={{ ...sideAction, type: isActiveSide ? 'highlighted' : isActive ? undefined : 'stealth' }}
        >
            {title}
        </LemonButtonWithSideAction>
    ) : (
        <LemonButton icon={icon} fullWidth type={isActive ? 'highlighted' : 'stealth'} onClick={onClick}>
            {title}
        </LemonButton>
    )
}

function Pages(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { showToolbarModal } = useActions(lemonadeLogic)

    return (
        <div className="Pages">
            {currentOrganization?.setup.is_active && (
                <>
                    <PageButton
                        title="Setup"
                        icon={<IconSettings />}
                        identifier="onboardingSetup"
                        onClick={urls.onboardingSetup()}
                    />
                    <Spacer />
                </>
            )}
            <PageButton title="Dashboards" icon={<IconGauge />} identifier="dashboards" onClick={urls.dashboards()} />
            <PageButton
                title="Insights"
                icon={<IconBarChart />}
                identifier="savedInsights"
                onClick={urls.savedInsights()}
                sideAction={{
                    icon: <IconPlus />,
                    onClick: urls.insightView(ViewType.TRENDS),
                    tooltip: 'New insight',
                    identifier: 'insights',
                }}
            />
            <PageButton
                title="Recordings"
                icon={<IconRecording />}
                identifier="sessionRecordings"
                onClick={urls.sessionRecordings()}
            />
            <PageButton
                title="Feature flags"
                icon={<IconFlag />}
                identifier="featureFlags"
                onClick={urls.featureFlags()}
            />
            <Spacer />
            <PageButton
                title="Events & actions"
                icon={<IconGroupedEvents />}
                identifier="events"
                onClick={urls.events()}
            />
            <PageButton title="Persons" icon={<IconPerson />} identifier="persons" onClick={urls.persons()} />
            <PageButton title="Cohorts" icon={<IconCohort />} identifier="cohorts" onClick={urls.cohorts()} />
            <PageButton
                title="Annotations"
                icon={<IconComment />}
                identifier="annotations"
                onClick={urls.annotations()}
            />
            <Spacer />
            {canViewPlugins(currentOrganization) && (
                <PageButton title="Plugins" icon={<IconExtension />} identifier="plugins" onClick={urls.plugins()} />
            )}
            <PageButton title="Toolbar" icon={<IconTools />} identifier="toolbar" onClick={showToolbarModal} />
            <PageButton
                title="Project settings"
                icon={<IconSettings />}
                identifier="projectSettings"
                onClick={urls.projectSettings()}
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
