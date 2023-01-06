import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { IconPlus, IconSettings } from 'lib/components/icons'
import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { LemonSnack } from 'lib/components/LemonSnack/LemonSnack'
import { organizationLogic } from 'scenes/organizationLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { AvailableFeature, TeamBasicType } from '~/types'
import { navigationLogic } from './navigationLogic'

export function ProjectName({ team }: { team: TeamBasicType }): JSX.Element {
    return (
        <div className="flex items-center">
            <span>{team.name}</span>
            {team.is_demo ? (
                <LemonSnack className="ml-2 text-xs shrink-0" color="primary-extralight">
                    Demo
                </LemonSnack>
            ) : null}
        </div>
    )
}

export function ProjectSwitcherOverlay(): JSX.Element {
    const { currentOrganization, projectCreationForbiddenReason } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)
    const { showCreateProjectModal, hideProjectSwitcher } = useActions(navigationLogic)

    return (
        <div className="project-switcher-container">
            <h5>Projects</h5>
            <LemonDivider />
            <CurrentProjectButton />
            {currentOrganization?.teams &&
                currentOrganization.teams
                    .filter((team) => team.id !== currentTeam?.id)
                    .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                    .map((team) => <OtherProjectButton key={team.id} team={team} />)}

            <LemonButton
                icon={<IconPlus />}
                fullWidth
                disabled={!!projectCreationForbiddenReason}
                tooltip={projectCreationForbiddenReason}
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
        </div>
    )
}

function CurrentProjectButton(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { push } = useActions(router)
    const { hideProjectSwitcher } = useActions(navigationLogic)

    return currentTeam ? (
        <LemonButtonWithSideAction
            active
            sideAction={{
                icon: <IconSettings className="text-muted-alt" />,
                tooltip: `Go to ${currentTeam.name} settings`,
                onClick: () => {
                    hideProjectSwitcher()
                    push(urls.projectSettings())
                },
            }}
            title={`Switch to project ${currentTeam.name}`}
            status="stealth"
            fullWidth
        >
            <ProjectName team={currentTeam} />
        </LemonButtonWithSideAction>
    ) : null
}

function OtherProjectButton({ team }: { team: TeamBasicType }): JSX.Element {
    const { updateCurrentTeam } = useActions(userLogic)
    const { hideProjectSwitcher } = useActions(navigationLogic)

    return (
        <LemonButtonWithSideAction
            onClick={() => {
                hideProjectSwitcher()
                updateCurrentTeam(team.id, '/')
            }}
            sideAction={{
                icon: <IconSettings className="text-muted-alt" />,
                tooltip: `Go to ${team.name} settings`,
                onClick: () => {
                    hideProjectSwitcher()
                    updateCurrentTeam(team.id, '/project/settings')
                },
            }}
            title={`Switch to project ${team.name}`}
            status="stealth"
            fullWidth
        >
            <ProjectName team={team} />
        </LemonButtonWithSideAction>
    )
}
