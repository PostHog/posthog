import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { IconPlus, IconSettings } from 'lib/components/icons'
import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { LemonRow } from 'lib/components/LemonRow'
import React from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { AvailableFeature, TeamBasicType } from '~/types'
import { lemonadeLogic } from '../lemonade/lemonadeLogic'
import './ScopeSwitchers.scss'

export function ProjectSwitcherOverlay(): JSX.Element {
    const { currentOrganization, isProjectCreationForbidden } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)
    const { showCreateProjectModal, hideProjectSwitcher } = useActions(lemonadeLogic)

    return (
        <div className="scope-switcher">
            <>
                <div className="scope-header">
                    <h4>Projects</h4>
                </div>
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
        </div>
    )
}

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
                    icon={<IconSettings style={{ color: 'var(--muted-alt)' }} />}
                />
            }
            fullWidth
        >
            <strong style={{ paddingRight: 8 }}>{currentTeam?.name}</strong>
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
                icon: <IconSettings style={{ color: 'var(--muted-alt)' }} />,
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
            <span style={{ paddingRight: 8 }}>{team.name}</span>
        </LemonButtonWithSideAction>
    )
}
