import { IconGear, IconPlus } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import {
    LemonMenuItemLeafCallback,
    LemonMenuItemLeafLink,
    LemonMenuOverlay,
    LemonMenuSection,
} from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'
import { removeFlagIdIfPresent, removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { useMemo } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature } from '~/types'

import { globalModalsLogic } from '../GlobalModals'

type MenuItemWithEnvName =
    | (LemonMenuItemLeafLink & {
          /** Extra menu item metadata, just for sorting the environments before we display them. */
          envName: string
      })
    | (LemonMenuItemLeafCallback & {
          envName?: never
      })

export function EnvironmentSwitcherOverlay({ onClickInside }: { onClickInside?: () => void }): JSX.Element {
    const { currentOrganization, projectCreationForbiddenReason } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateProjectModal, showCreateEnvironmentModal } = useActions(globalModalsLogic)
    const { location } = useValues(router)

    const projectSections = useMemo<LemonMenuSection[] | null>(() => {
        if (!currentOrganization) {
            return null
        }
        const projectMapping = currentOrganization.projects.reduce<Record<number, [string, MenuItemWithEnvName[]]>>(
            (acc, project) => {
                acc[project.id] = [project.name, []]
                return acc
            },
            {}
        )

        for (const team of currentOrganization.teams) {
            const [projectName, envItems] = projectMapping[team.project_id]
            envItems.push({
                label: (
                    <>
                        {team.name}
                        {team.is_demo && (
                            <LemonTag className="ml-1.5" type="highlight">
                                DEMO
                            </LemonTag>
                        )}
                    </>
                ),
                envName: team.name,
                active: currentTeam?.id === team.id,
                to: determineProjectSwitchUrl(location.pathname, team.id),
                tooltip:
                    currentTeam?.id === team.id
                        ? 'Currently active environment'
                        : `Switch to the ${team.name} environment of ${projectName}`,
                onClick: onClickInside,
                sideAction: {
                    icon: <IconGear />,
                    tooltip: `Go to ${team.name} settings`,
                    tooltipPlacement: 'right',
                    onClick: onClickInside,
                    to: urls.project(team.id, urls.settings()),
                },
                icon: <div className="size-6" />, // Icon-sized filler
            })
        }
        const sortedProjects = Object.entries(projectMapping).sort(
            // The project with the active environment always comes first - otherwise sorted alphabetically by name
            ([, [aProjectName, aEnvItems]], [, [bProjectName]]) =>
                aEnvItems.find((item) => item.active) ? -Infinity : aProjectName.localeCompare(bProjectName)
        )
        const projectSectionsResult = []
        for (const [projectId, [projectName, envItems]] of sortedProjects) {
            // The environment that's active always comes first - otherwise sorted alphabetically by name
            envItems.sort((a, b) => (b.active ? Infinity : a.envName!.localeCompare(b.envName!)))
            envItems.unshift({
                label: projectName,
                icon: <UploadedLogo name={projectName} entityId={projectId} outlinedLettermark />,
                disabledReason: 'Select an environment of this project',
                onClick: () => {},
                sideAction: {
                    icon: <IconPlus />,
                    tooltip: `New environment within ${projectName}`,
                    tooltipPlacement: 'right',
                    disabledReason: projectCreationForbiddenReason?.replace('project', 'environment'),
                    onClick: () => {
                        onClickInside?.()
                        guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, showCreateEnvironmentModal, {
                            currentUsage: currentOrganization?.teams?.length,
                        })
                    },
                    'data-attr': 'new-environment-button',
                },
            })
            projectSectionsResult.push({ items: envItems })
        }
        return projectSectionsResult
    }, [currentTeam, currentOrganization, location])

    if (!projectSections) {
        return <Spinner />
    }

    return (
        <LemonMenuOverlay
            items={[
                { title: 'Projects', items: [] },
                ...projectSections,
                {
                    icon: <IconPlus />,
                    label: 'New project',
                    disabledReason: projectCreationForbiddenReason,
                    onClick: () => {
                        onClickInside?.()
                        // TODO: Use showCreateEnvironmentModal
                        guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, showCreateProjectModal, {
                            currentUsage: currentOrganization?.teams?.length,
                        })
                    },
                    'data-attr': 'new-project-button',
                },
            ]}
        />
    )
}

function determineProjectSwitchUrl(pathname: string, newTeamId: number): string {
    // NOTE: There is a tradeoff here - because we choose keep the whole path it could be that the
    // project switch lands on something like insight/abc that won't exist.
    // On the other hand, if we remove the ID, it could be that someone opens a page, realizes they're in the wrong project
    // and after switching is on a different page than before.
    let route = removeProjectIdIfPresent(pathname)
    route = removeFlagIdIfPresent(route)
    return urls.project(newTeamId, route)
}
