import { useActions, useValues } from 'kea'
import { router, combineUrl } from 'kea-router'
import { IconPlus, IconSettings } from 'lib/components/icons'
import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { LemonSnack } from 'lib/components/LemonSnack/LemonSnack'
import { organizationLogic } from 'scenes/organizationLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
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

export function ProjectSwitcherOverlay({ onClose }: { onClose: () => void }): JSX.Element {
    const { currentOrganization, projectCreationForbiddenReason } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)
    const { showCreateProjectModal } = useActions(navigationLogic)

    return (
        <div className="project-switcher-container space-y-px">
            <h5>Projects</h5>
            <LemonDivider />
            <CurrentProjectButton onClick={onClose} />
            {currentOrganization?.teams &&
                currentOrganization.teams
                    .filter((team) => team.id !== currentTeam?.id)
                    .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                    .map((team) => <OtherProjectButton key={team.id} team={team} onClick={onClose} />)}

            <LemonButton
                icon={<IconPlus />}
                fullWidth
                disabled={!!projectCreationForbiddenReason}
                tooltip={projectCreationForbiddenReason}
                onClick={() => {
                    onClose()
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

function CurrentProjectButton({ onClick }: { onClick: () => void }): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { push } = useActions(router)

    return currentTeam ? (
        <LemonButtonWithSideAction
            active
            sideAction={{
                icon: <IconSettings className="text-muted-alt" />,
                tooltip: `Go to ${currentTeam.name} settings`,
                onClick: () => {
                    onClick()
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

function OtherProjectButton({ team, onClick }: { team: TeamBasicType; onClick: () => void }): JSX.Element {
    const { location, searchParams, hashParams } = useValues(router)

    const projectSwitchUrl = combineUrl(
        location.pathname,
        {
            ...searchParams,
            pid: team.id,
        },
        hashParams
    ).url

    return (
        <LemonButtonWithSideAction
            to={projectSwitchUrl}
            onClick={onClick}
            disableClientSideRouting
            sideAction={{
                icon: <IconSettings className="text-muted-alt" />,
                tooltip: `Go to ${team.name} settings`,
                to: `/project/settings?tid=${team.id}`,
                disableClientSideRouting: true,
                onClick: onClick,
            }}
            title={`Switch to project ${team.name}`}
            status="stealth"
            fullWidth
            disabled={!team.effective_membership_level}
        >
            <ProjectName team={team} />
        </LemonButtonWithSideAction>
    )
}
