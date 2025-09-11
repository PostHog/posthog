import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconCheck, IconCornerDownRight, IconGear, IconPlusSmall, IconWarning } from '@posthog/icons'
import { LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'
import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonGroupPrimitive, ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { Combobox } from 'lib/ui/Combobox/Combobox'
import { DropdownMenuOpenIndicator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from 'lib/ui/PopoverPrimitive/PopoverPrimitive'
import { cn } from 'lib/utils/css-classes'
import { getProjectSwitchTargetUrl } from 'lib/utils/router-utils'
import { organizationLogic } from 'scenes/organizationLogic'
import { environmentRollbackModalLogic } from 'scenes/settings/environment/environmentRollbackModalLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature, TeamPublicType } from '~/types'

import { globalModalsLogic } from '../GlobalModals'
import { TeamBasicTypeWithProjectName, environmentSwitcherLogic } from './environmentsSwitcherLogic'

/**
 * Regex matching a possible emoji (any emoji) at the beginning of the string.
 * Examples: In "👋 Hello", match group 1 is "👋". In "Hello" or "Hello 👋", there are no matches.
 * From https://stackoverflow.com/a/67705964/351526
 */
const EMOJI_INITIAL_REGEX =
    /^(\u00a9|\u00ae|[\u25a0-\u27bf]|\ud83c[\ud000-\udfff]|\ud83d[\ud000-\udfff]|\ud83e[\ud000-\udfff]) /

export function EnvironmentSwitcherOverlay({
    buttonProps = { className: 'font-semibold' },
    onClickInside,
    iconOnly = false,
}: {
    buttonProps?: ButtonPrimitiveProps
    onClickInside?: () => void
    iconOnly?: boolean
}): JSX.Element {
    const { searchedProjectsMap } = useValues(environmentSwitcherLogic)
    const { currentOrganization, projectCreationForbiddenReason } = useValues(organizationLogic)
    const { currentTeam, currentProject } = useValues(teamLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateProjectModal, showCreateEnvironmentModal } = useActions(globalModalsLogic)
    const { hasEnvironmentsRollbackFeature } = useValues(environmentRollbackModalLogic)
    const { openModal } = useActions(environmentRollbackModalLogic)
    const [open, setOpen] = useState(false)

    const { location } = useValues(router)

    const [environmentsRollbackNotice, currentProjectSection, otherProjectsSection] = useMemo<
        [JSX.Element | null, JSX.Element | null, JSX.Element | null]
    >(() => {
        if (!currentOrganization || !currentTeam?.project_id) {
            return [null, null, null]
        }

        const currentProjectItems: Array<JSX.Element> = []
        const matchForCurrentProject = searchedProjectsMap.get(currentTeam.project_id)
        if (matchForCurrentProject) {
            const [projectName, projectTeams] = matchForCurrentProject
            const projectNameWithoutEmoji = projectName.replace(EMOJI_INITIAL_REGEX, '').trim()
            const projectNameEmojiMatch = projectName.match(EMOJI_INITIAL_REGEX)?.[1]
            currentProjectItems.push(
                <>
                    <Label intent="menu" className="px-2 mt-2">
                        Current project
                    </Label>
                    <div className="-mx-1 my-1 h-px bg-border-primary shrink-0" />

                    <Combobox.Group value={[projectName]}>
                        <ButtonGroupPrimitive fullWidth className="[&>span]:contents">
                            <Combobox.Item asChild>
                                <ButtonPrimitive
                                    menuItem
                                    active
                                    hasSideActionRight
                                    tooltipPlacement="right"
                                    tooltip="Select or create an environment of this project below"
                                    data-attr="environment-switcher-current-project-button"
                                    className="pr-12"
                                    disabled
                                >
                                    <IconCheck className="text-tertiary" />
                                    {projectNameEmojiMatch ? (
                                        <div className="size-5 text-xl leading-5 text-center">
                                            {projectNameEmojiMatch}
                                        </div>
                                    ) : (
                                        <UploadedLogo
                                            name={projectName}
                                            entityId={currentTeam.project_id}
                                            outlinedLettermark
                                            size="small"
                                        />
                                    )}
                                    <span className="truncate">{projectNameWithoutEmoji}</span>
                                </ButtonPrimitive>
                            </Combobox.Item>

                            <Combobox.Item asChild>
                                <Link
                                    buttonProps={{
                                        iconOnly: true,
                                        isSideActionRight: true,
                                    }}
                                    tooltip={`View settings for project: ${projectNameWithoutEmoji}`}
                                    tooltipPlacement="right"
                                    to={urls.project(currentTeam.project_id, urls.settings('project'))}
                                    data-attr="environment-switcher-current-project-settings-button"
                                >
                                    <IconGear className="text-tertiary" />
                                </Link>
                            </Combobox.Item>
                        </ButtonGroupPrimitive>
                    </Combobox.Group>
                </>
            )
            for (const team of projectTeams) {
                currentProjectItems.push(
                    convertTeamToMenuItem(team, currentTeam, () => {
                        setOpen(false)
                    })
                )
            }
            currentProjectItems.push(
                <ButtonPrimitive
                    menuItem
                    data-attr="new-environment-button"
                    tooltipPlacement="right"
                    className="shrink-0"
                    tooltip="We're temporarily pausing new environments as we make some improvements! Stay tuned for more. In the meantime, you can create new projects."
                    disabled
                    onClick={() => {
                        guardAvailableFeature(AvailableFeature.ENVIRONMENTS, showCreateEnvironmentModal, {
                            currentUsage: currentOrganization?.teams?.filter(
                                (team) => team.project_id === currentTeam.project_id
                            ).length,
                        })
                    }}
                >
                    <IconBlank />
                    <IconPlusSmall />
                    New environment in project
                </ButtonPrimitive>
            )
        }

        const otherProjectsItems: Array<JSX.Element> = []

        for (const [projectId, [projectName, projectTeams]] of searchedProjectsMap.entries()) {
            if (projectId === currentTeam?.project_id) {
                continue
            }
            const projectNameWithoutEmoji = projectName.replace(EMOJI_INITIAL_REGEX, '').trim()
            const projectNameEmojiMatch = projectName.match(EMOJI_INITIAL_REGEX)?.[1]

            // Add "Other projects" label just once, before any other projects are added
            if (projectTeams.length > 0 && otherProjectsItems.length === 0) {
                otherProjectsItems.push(
                    <>
                        <Label intent="menu" className="px-2 mt-2">
                            Other projects
                        </Label>
                        <div className="-mx-1.5 my-1 h-px bg-border-primary shrink-0" />
                    </>
                )
            }

            otherProjectsItems.push(
                <>
                    <Combobox.Group value={[projectName]} key={projectId}>
                        <ButtonGroupPrimitive fullWidth className="[&>span]:contents">
                            <Combobox.Item asChild>
                                <ButtonPrimitive
                                    menuItem
                                    hasSideActionRight
                                    className="pr-12"
                                    disabled
                                    tooltip="Select an environment for this project below"
                                    tooltipPlacement="right"
                                    data-attr="environment-switcher-other-project-button"
                                >
                                    {projectNameEmojiMatch ? (
                                        <div className="size-6 text-xl leading-6 text-center">
                                            {projectNameEmojiMatch}
                                        </div>
                                    ) : (
                                        <UploadedLogo
                                            name={projectName}
                                            entityId={projectId}
                                            outlinedLettermark
                                            size="small"
                                        />
                                    )}
                                    <span className="truncate">{projectNameWithoutEmoji}</span>
                                </ButtonPrimitive>
                            </Combobox.Item>
                            <Combobox.Item asChild>
                                <Link
                                    buttonProps={{
                                        iconOnly: true,
                                        isSideActionRight: true,
                                    }}
                                    tooltip="View settings for this project"
                                    tooltipPlacement="right"
                                    to={urls.project(projectId, urls.settings('project'))}
                                    data-attr="environment-switcher-other-project-settings-button"
                                >
                                    <IconGear className="text-tertiary" />
                                </Link>
                            </Combobox.Item>
                        </ButtonGroupPrimitive>
                    </Combobox.Group>
                </>
            )
            for (const team of projectTeams) {
                otherProjectsItems.push(convertTeamToMenuItem(team, currentTeam))
            }
        }
        return [
            hasEnvironmentsRollbackFeature ? (
                <Combobox.Group value={['warning']} key="warning">
                    <Combobox.Item asChild>
                        <ButtonPrimitive menuItem onClick={openModal} variant="danger" className="h-auto">
                            <IconWarning />
                            We're rolling back the environments beta
                        </ButtonPrimitive>
                    </Combobox.Item>
                </Combobox.Group>
            ) : null,
            currentProjectItems.length ? <>{currentProjectItems}</> : null,
            otherProjectsItems.length ? <>{otherProjectsItems}</> : null,
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
        <PopoverPrimitive open={open} onOpenChange={setOpen}>
            <PopoverPrimitiveTrigger asChild>
                <ButtonPrimitive
                    data-attr="environment-switcher-button"
                    size={iconOnly ? 'base' : 'sm'}
                    iconOnly={iconOnly}
                    {...buttonProps}
                    className={cn('flex-1 max-w-fit min-w-[40px]', iconOnly ? 'min-w-auto' : '', buttonProps.className)}
                >
                    {iconOnly ? (
                        <div className="Lettermark bg-[var(--color-bg-fill-button-tertiary-active)] w-5 h-5 ">
                            {currentTeam.name.slice(0, 1).toLocaleUpperCase()}
                        </div>
                    ) : (
                        <span className="truncate">{currentProject?.name ?? 'Project'}</span>
                    )}
                    {!iconOnly && <DropdownMenuOpenIndicator />}
                </ButtonPrimitive>
            </PopoverPrimitiveTrigger>
            <PopoverPrimitiveContent align="start" className="w-[300px] sm:w-[500px] max-w-[300px] sm:max-w-[500px]">
                <Combobox>
                    <Combobox.Search placeholder="Filter projects & environments..." />
                    <Combobox.Content>
                        <Combobox.Empty>No projects or environments found</Combobox.Empty>

                        {environmentsRollbackNotice}

                        <Combobox.Item
                            asChild
                            onClick={() =>
                                guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, showCreateProjectModal, {
                                    currentUsage: currentOrganization?.teams?.length,
                                })
                            }
                        >
                            <ButtonPrimitive
                                menuItem
                                data-attr="new-project-button"
                                tooltip="Create a new project"
                                tooltipPlacement="right"
                                className="shrink-0"
                                disabled={!!projectCreationForbiddenReason}
                            >
                                <IconPlusSmall className="text-tertiary" />
                                New project
                            </ButtonPrimitive>
                        </Combobox.Item>

                        {currentProjectSection}
                        {otherProjectsSection}
                    </Combobox.Content>
                </Combobox>
            </PopoverPrimitiveContent>
        </PopoverPrimitive>
    )
}

function convertTeamToMenuItem(
    team: TeamBasicTypeWithProjectName,
    currentTeam: TeamPublicType,
    handleActiveClick?: () => void
): JSX.Element {
    const active = team.id === currentTeam.id
    return (
        <>
            <Combobox.Group value={[team.name]}>
                <ButtonGroupPrimitive fullWidth className="[&>span]:contents">
                    <Combobox.Item asChild>
                        <Link
                            buttonProps={{
                                menuItem: true,
                                hasSideActionRight: true,
                                className: 'pr-12 w-full',
                                active,
                            }}
                            tooltip={active ? 'Currently active environment' : 'Switch to this environment'}
                            tooltipPlacement="right"
                            to={determineProjectSwitchUrl(location.pathname, team.id)}
                            onClick={active ? handleActiveClick : undefined}
                            data-attr="environment-switcher-environment-button"
                        >
                            <IconBlank />
                            <IconCornerDownRight className="text-tertiary" />
                            <LemonTag size="small" className="border-text-3000 uppercase">
                                {team.name}
                            </LemonTag>
                        </Link>
                    </Combobox.Item>

                    <Combobox.Item asChild>
                        <Link
                            buttonProps={{
                                iconOnly: true,
                                isSideActionRight: true,
                            }}
                            tooltip={`Go to this environment's settings`}
                            tooltipPlacement="right"
                            to={urls.project(team.id, urls.settings('environment'))}
                            onClick={active ? handleActiveClick : undefined}
                            data-attr="environment-switcher-environment-settings-button"
                        >
                            <IconGear className="text-tertiary" />
                        </Link>
                    </Combobox.Item>
                </ButtonGroupPrimitive>
            </Combobox.Group>
        </>
    )
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
