import { IconChevronDown, IconCornerDownRight, IconGear, IconPlus, IconWarning } from '@posthog/icons'
import { LemonInput, LemonTag, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonMenuItem, LemonMenuOverlay, LemonMenuSection } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'
import { getProjectSwitchTargetUrl } from 'lib/utils/router-utils'
import { useMemo } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { environmentRollbackModalLogic } from 'scenes/settings/environment/environmentRollbackModalLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature, TeamPublicType } from '~/types'

import { globalModalsLogic } from '../GlobalModals'
import { environmentSwitcherLogic, TeamBasicTypeWithProjectName } from './environmentsSwitcherLogic'

/**
 * Regex matching a possible emoji (any emoji) at the beginning of the string.
 * Examples: In "👋 Hello", match group 1 is "👋". In "Hello" or "Hello 👋", there are no matches.
 * From https://stackoverflow.com/a/67705964/351526
 */
const EMOJI_INITIAL_REGEX =
    /^(\u00a9|\u00ae|[\u25a0-\u27bf]|\ud83c[\ud000-\udfff]|\ud83d[\ud000-\udfff]|\ud83e[\ud000-\udfff]) /

export function EnvironmentSwitcherOverlay({ onClickInside }: { onClickInside?: () => void }): JSX.Element {
    const { searchedProjectsMap } = useValues(environmentSwitcherLogic)
    const { currentOrganization, projectCreationForbiddenReason } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateProjectModal, showCreateEnvironmentModal } = useActions(globalModalsLogic)
    const { hasEnvironmentsRollbackFeature } = useValues(environmentRollbackModalLogic)
    const { openModal } = useActions(environmentRollbackModalLogic)

    const { location } = useValues(router)

    const [environmentsRollbackNotice, currentProjectSection, otherProjectsSection] = useMemo<
        [LemonMenuSection | null, LemonMenuSection | null, LemonMenuSection | null]
    >(() => {
        if (!currentOrganization || !currentTeam?.project_id) {
            return [null, null, null]
        }

        const currentProjectItems: LemonMenuItem[] = []
        const matchForCurrentProject = searchedProjectsMap.get(currentTeam.project_id)
        if (matchForCurrentProject) {
            const [projectName, projectTeams] = matchForCurrentProject
            const projectNameWithoutEmoji = projectName.replace(EMOJI_INITIAL_REGEX, '').trim()
            const projectNameEmojiMatch = projectName.match(EMOJI_INITIAL_REGEX)?.[1]
            currentProjectItems.push({
                label: projectNameWithoutEmoji,
                icon: projectNameEmojiMatch ? (
                    <div className="size-5 text-xl leading-5 text-center">{projectNameEmojiMatch}</div>
                ) : (
                    <UploadedLogo
                        name={projectName}
                        entityId={currentTeam.project_id}
                        outlinedLettermark
                        size="small"
                    />
                ),
                disabledReason: 'Select or create an environment of this project below',
                sideAction: {
                    icon: <IconGear />,
                    tooltip: "Go to this project's settings",
                    onClick: onClickInside,
                    to: urls.project(currentTeam.project_id, urls.settings('project')),
                },
                className: 'opacity-100', // This button is not disabled in a traditional sense here
            })
            for (const team of projectTeams) {
                currentProjectItems.push(convertTeamToMenuItem(team, currentTeam, onClickInside))
            }
            currentProjectItems.push({
                icon: <IconPlus />,
                label: 'New environment in project',
                onClick: () => {
                    onClickInside?.()
                    guardAvailableFeature(AvailableFeature.ENVIRONMENTS, showCreateEnvironmentModal, {
                        currentUsage: currentOrganization?.teams?.filter(
                            (team) => team.project_id === currentTeam.project_id
                        ).length,
                    })
                },
                disabledReason:
                    "We're temporarily pausing new environments as we make some improvements! Stay tuned for more. In the meantime, you can create new projects.",
                'data-attr': 'new-environment-button',
            })
        }

        const otherProjectsItems: LemonMenuItem[] = []
        for (const [projectId, [projectName, projectTeams]] of searchedProjectsMap.entries()) {
            if (projectId === currentTeam?.project_id) {
                continue
            }
            const projectNameWithoutEmoji = projectName.replace(EMOJI_INITIAL_REGEX, '').trim()
            const projectNameEmojiMatch = projectName.match(EMOJI_INITIAL_REGEX)?.[1]
            otherProjectsItems.push({
                key: projectId,
                label: (
                    <>
                        {projectNameWithoutEmoji}
                        <LemonTag size="small" className="border-text-3000 uppercase ml-1.5">
                            {projectTeams[0].name}
                        </LemonTag>
                        {projectTeams.length > 1 && (
                            <span className="text-xs font-medium ml-1.5">+ {projectTeams.length - 1}</span>
                        )}
                    </>
                ),
                icon: projectNameEmojiMatch ? (
                    <div className="size-6 text-xl leading-6 text-center">{projectNameEmojiMatch}</div>
                ) : (
                    <UploadedLogo name={projectName} entityId={projectId} outlinedLettermark size="small" />
                ),
                to: determineProjectSwitchUrl(location.pathname, projectTeams[0].id),
                onClick: onClickInside,
                tooltip: `Switch to this project & its ${projectTeams.length > 1 ? 'first' : 'only'} environment`,
                sideAction:
                    projectTeams.length > 1
                        ? {
                              icon: <IconChevronDown />,
                              divider: true,
                              dropdown: {
                                  overlay: (
                                      <LemonMenuOverlay
                                          items={projectTeams.map((team) =>
                                              convertTeamToMenuItem(team, currentTeam, onClickInside)
                                          )}
                                      />
                                  ),
                                  placement: 'bottom-start',
                              },
                          }
                        : null,
            })
        }
        return [
            hasEnvironmentsRollbackFeature
                ? {
                      items: [
                          {
                              label: `We're rolling back the environments beta`,
                              onClick: openModal,
                              status: 'danger',
                              icon: <IconWarning />,
                          },
                      ],
                  }
                : null,
            currentProjectItems.length ? { title: 'Current project', items: currentProjectItems } : null,
            otherProjectsItems.length ? { title: 'Other projects', items: otherProjectsItems } : null,
        ]
    }, [
        currentOrganization,
        currentTeam,
        searchedProjectsMap,
        projectCreationForbiddenReason,
        location.pathname,
        onClickInside,
        guardAvailableFeature,
        showCreateEnvironmentModal,
        hasEnvironmentsRollbackFeature,
        openModal,
    ])

    if (!currentOrganization || !currentTeam) {
        return <Spinner />
    }

    return (
        <LemonMenuOverlay
            items={[
                {
                    items: [{ label: EnvironmentSwitcherSearch }],
                },
                environmentsRollbackNotice,
                currentProjectSection,
                otherProjectsSection,
                {
                    icon: <IconPlus />,
                    label: 'New project',
                    disabledReason: projectCreationForbiddenReason,
                    onClick: () => {
                        onClickInside?.()
                        guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, showCreateProjectModal, {
                            currentUsage: currentOrganization?.projects?.length,
                        })
                    },
                    'data-attr': 'new-project-button',
                },
            ]}
        />
    )
}

function convertTeamToMenuItem(
    team: TeamBasicTypeWithProjectName,
    currentTeam: TeamPublicType,
    onClickInside?: () => void
): LemonMenuItem {
    return {
        label: (
            <>
                <LemonTag size="small" className="border-text-3000 uppercase">
                    {team.name}
                </LemonTag>
            </>
        ),
        key: team.id,
        active: team.id === currentTeam.id,
        to: determineProjectSwitchUrl(location.pathname, team.id),
        icon: <IconCornerDownRight className="ml-1 -mr-1 -mt-[5px]" />,
        tooltip:
            team.id === currentTeam.id
                ? 'Currently active environment'
                : team.project_id === currentTeam.project_id
                ? 'Switch to this environment'
                : 'Switch to this environment of the project',
        onClick: onClickInside,
        sideAction: {
            icon: <IconGear />,
            tooltip: "Go to this environment's settings",
            onClick: onClickInside,
            to: urls.project(team.id, urls.settings('environment')),
        },
    }
}

function determineProjectSwitchUrl(pathname: string, newTeamId: number): string {
    const { currentTeam } = teamLogic.values
    const { currentOrganization } = organizationLogic.values

    // Find the target team's project ID
    let targetTeamProjectId: number | null = null
    if (currentOrganization?.teams) {
        const targetTeam = currentOrganization.teams.find((team) => team.id === newTeamId)
        if (targetTeam) {
            targetTeamProjectId = targetTeam.project_id
        }
    }

    return getProjectSwitchTargetUrl(pathname, newTeamId, currentTeam?.project_id, targetTeamProjectId)
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
