import { IconChevronRight, IconFolderOpen, IconGear, IconPlusSmall } from '@posthog/icons'
import { LemonSnack, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { getProjectSwitchTargetUrl } from 'lib/utils/router-utils'
import { useMemo } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { globalModalsLogic } from '~/layout/GlobalModals'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { AvailableFeature, TeamBasicType } from '~/types'

export function ProjectName({ team }: { team: TeamBasicType }): JSX.Element {
    return (
        <div className="flex items-center max-w-full">
            <span className="truncate">{team.name}</span>
            {team.is_demo ? <LemonSnack className="ml-2 text-xs shrink-0">Demo</LemonSnack> : null}
        </div>
    )
}

function OtherProjectButton({ team }: { team: TeamBasicType }): JSX.Element {
    const { location } = useValues(router)
    const { currentTeam } = useValues(teamLogic)

    const relativeOtherProjectPath = useMemo(() => {
        return getProjectSwitchTargetUrl(location.pathname, team.id, currentTeam?.project_id, team.project_id)
    }, [location.pathname, team.id, team.project_id, currentTeam?.project_id])

    return (
        <ButtonGroupPrimitive menuItem fullWidth>
            <DropdownMenuItem asChild>
                <Link
                    buttonProps={{
                        menuItem: true,
                        hasSideActionRight: true,
                    }}
                    tooltip={`Switch to project: ${team.name}`}
                    tooltipPlacement="right"
                    to={relativeOtherProjectPath}
                >
                    <ProjectName team={team} />
                </Link>
            </DropdownMenuItem>
            <Link
                buttonProps={{
                    iconOnly: true,
                    isSideActionRight: true,
                }}
                tooltip={`View settings for project: ${team.name}`}
                tooltipPlacement="right"
                to={urls.project(team.id, urls.settings('project'))}
            >
                <IconGear />
            </Link>
        </ButtonGroupPrimitive>
    )
}

export function ProjectDropdownMenu(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { closeAccountPopover } = useActions(navigationLogic)
    const { showCreateProjectModal } = useActions(globalModalsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)

    return isAuthenticatedTeam(currentTeam) ? (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive>
                    <IconFolderOpen className="text-tertiary" />
                    Project
                    <IconChevronRight
                        className={`
                        size-3 
                        text-secondary 
                        rotate-90 
                        group-data-[state=open]/button-primitive:rotate-270 
                        transition-transform 
                        duration-200 
                        prefers-reduced-motion:transition-none
                    `}
                    />
                </ButtonPrimitive>
            </DropdownMenuTrigger>

            <DropdownMenuContent
                loop
                align="start"
                className={`
                min-w-[200px] 
                max-w-[var(--project-panel-inner-width)] 
            `}
            >
                <DropdownMenuLabel>Projects</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                    <ButtonGroupPrimitive fullWidth>
                        <ButtonPrimitive
                            menuItem
                            active
                            disabled
                            hasSideActionRight
                            tooltip={`Current project: ${currentTeam.name}`}
                            tooltipPlacement="right"
                        >
                            <ProjectName team={currentTeam} />
                        </ButtonPrimitive>
                        <Link
                            buttonProps={{
                                active: true,
                                iconOnly: true,
                                isSideActionRight: true,
                            }}
                            tooltip={`View settings for project: ${currentTeam.name}`}
                            tooltipPlacement="right"
                            to={urls.project(currentTeam.id, urls.settings('project'))}
                        >
                            <IconGear className="text-tertiary" />
                        </Link>
                    </ButtonGroupPrimitive>
                </DropdownMenuItem>

                {currentOrganization?.teams &&
                    currentOrganization.teams
                        .filter((team) => team.id !== currentTeam?.id)
                        .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                        .map((team) => <OtherProjectButton key={team.id} team={team} />)}

                {preflight?.can_create_org && (
                    <DropdownMenuItem
                        asChild
                        onClick={() =>
                            guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, () => {
                                closeAccountPopover()
                                showCreateProjectModal()
                            })
                        }
                    >
                        <ButtonPrimitive
                            menuItem
                            data-attr="new-project-button"
                            tooltip="Create a new project"
                            tooltipPlacement="right"
                        >
                            <IconPlusSmall className="text-tertiary" />
                            New project
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    ) : null
}
