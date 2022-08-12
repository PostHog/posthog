import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { IconPlus, IconSettings } from 'lib/components/icons'
import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import React from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { AvailableFeature, TeamBasicType } from '~/types'
import { navigationLogic } from './navigationLogic'

export function ProjectSwitcherOverlay(): JSX.Element {
    const { currentOrganization, isProjectCreationForbidden } = useValues(organizationLogic)
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
                disabled={isProjectCreationForbidden}
                title={
                    isProjectCreationForbidden
                        ? "You aren't allowed to create a project. Your organization access level is probably insufficient."
                        : undefined
                }
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
            {currentTeam.name}
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
            disabled={!team.effective_membership_level}
        >
            {team.name}
        </LemonButtonWithSideAction>
    )
}
