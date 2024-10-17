import { IconGear, IconPlus } from '@posthog/icons'
import { LemonInput, LemonTag, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonMenuItem, LemonMenuOverlay, LemonMenuSection } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'
import { removeFlagIdIfPresent, removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { useMemo } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature } from '~/types'

import { globalModalsLogic } from '../GlobalModals'
import { environmentSwitcherLogic } from './environmentsSwitcherLogic'

/**
 * Regex matching a possible emoji (any emoji) at the beginning of the string.
 * Examples: In "👋 Hello", match group 1 is "👋". In "Hello" or "Hello 👋", there are no matches.
 * From https://stackoverflow.com/a/67705964/351526
 */
const EMOJI_INITIAL_REGEX =
    /^(\u00a9|\u00ae|[\u25a0-\u27bf]|\ud83c[\ud000-\udfff]|\ud83d[\ud000-\udfff]|\ud83e[\ud000-\udfff]) /

export function EnvironmentSwitcherOverlay({ onClickInside }: { onClickInside?: () => void }): JSX.Element {
    const { sortedProjectsMap } = useValues(environmentSwitcherLogic)
    const { currentOrganization, projectCreationForbiddenReason } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateProjectModal, showCreateEnvironmentModal } = useActions(globalModalsLogic)
    const { location } = useValues(router)

    const projectSections = useMemo<LemonMenuSection[] | null>(() => {
        if (!currentOrganization) {
            return null
        }

        const projectSectionsResult: LemonMenuSection[] = []
        for (const [projectId, [projectName, projectTeams]] of sortedProjectsMap.entries()) {
            const projectNameWithoutEmoji = projectName.replace(EMOJI_INITIAL_REGEX, '').trim()
            const projectNameEmojiMatch = projectName.match(EMOJI_INITIAL_REGEX)?.[1]
            const projectItems: LemonMenuItem[] = [
                {
                    label: <span className="opacity-[var(--opacity-disabled)]">{projectNameWithoutEmoji}</span>,
                    icon: projectNameEmojiMatch ? (
                        <div className="size-6 text-xl leading-6 text-center">{projectNameEmojiMatch}</div>
                    ) : (
                        <UploadedLogo name={projectName} entityId={projectId} outlinedLettermark />
                    ),
                    disabledReason: 'Select an environment of this project below',
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
                    className: 'opacity-100',
                },
            ]
            for (const team of projectTeams) {
                projectItems.push({
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
                    key: team.id,
                    active: currentTeam?.id === team.id,
                    to: determineProjectSwitchUrl(location.pathname, team.id),
                    tooltip:
                        currentTeam?.id === team.id ? (
                            'Currently active environment'
                        ) : (
                            <>
                                Switch to environment <strong>{team.name}</strong>
                                {currentTeam?.project_id !== team.project_id && (
                                    <>
                                        {' '}
                                        of project <strong>{projectName}</strong>
                                    </>
                                )}
                            </>
                        ),
                    onClick: onClickInside,
                    sideAction: {
                        icon: <IconGear />,
                        tooltip: "Go to this environment's settings",
                        tooltipPlacement: 'right',
                        onClick: onClickInside,
                        to: urls.project(team.id, urls.settings()),
                    },
                    icon: <div className="size-6" />, // Icon-sized filler
                })
            }
            projectSectionsResult.push({ key: projectId, items: projectItems })
        }
        return projectSectionsResult
    }, [
        currentOrganization,
        sortedProjectsMap,
        projectCreationForbiddenReason,
        onClickInside,
        guardAvailableFeature,
        showCreateEnvironmentModal,
        currentTeam?.id,
        currentTeam?.project_id,
        location.pathname,
    ])

    if (!projectSections) {
        return <Spinner />
    }

    return (
        <LemonMenuOverlay
            items={[
                {
                    items: [{ label: EnvironmentSwitcherSearch }],
                },
                ...projectSections,
                {
                    icon: <IconPlus />,
                    label: 'New project',
                    disabledReason: projectCreationForbiddenReason,
                    onClick: () => {
                        onClickInside?.()
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

function EnvironmentSwitcherSearch(): JSX.Element {
    const { environmentSwitcherSearch } = useValues(environmentSwitcherLogic)
    const { setEnvironmentSwitcherSearch } = useActions(environmentSwitcherLogic)

    return (
        <LemonInput
            value={environmentSwitcherSearch}
            onChange={setEnvironmentSwitcherSearch}
            type="search"
            fullWidth
            autoFocus
            placeholder="Search projects & environments"
            className="min-w-64"
            onClick={(e) => {
                e.stopPropagation() // Prevent dropdown from closing
            }}
        />
    )
}
