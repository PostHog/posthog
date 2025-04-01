import { IconChevronRight, IconFolderOpen, IconGear, IconPlusSmall } from '@posthog/icons'
import { LemonSnack } from '@posthog/lemon-ui'
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
        <div className="flex items-center">
            <span>{team.name}</span>
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
        <DropdownMenuItem asChild>
            <ButtonGroupPrimitive menuItem fullWidth groupVariant="side-action-group">
                <ButtonPrimitive menuItem href={relativeOtherProjectPath} sideActionLeft>
                    <ProjectName team={team} />
                </ButtonPrimitive>
                <ButtonPrimitive href={urls.project(team.id, urls.settings('project'))} iconOnly sideActionRight>
                    <IconGear />
                </ButtonPrimitive>
            </ButtonGroupPrimitive>
        </DropdownMenuItem>
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
                    <IconChevronRight className="size-3 text-secondary rotate-90 group-data-[state=open]/button-primitive:rotate-270 transition-transform duration-200 prefers-reduced-motion:transition-none" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>

            <DropdownMenuContent loop align="start" className="min-w-[200px]">
                <DropdownMenuLabel>Projects</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <div className="flex flex-col gap-px">
                    <DropdownMenuItem asChild>
                        <ButtonGroupPrimitive fullWidth groupVariant="side-action-group">
                            <ButtonPrimitive menuItem active disabled sideActionLeft>
                                <ProjectName team={currentTeam} />
                            </ButtonPrimitive>
                            <ButtonPrimitive
                                active
                                href={urls.project(currentTeam.id, urls.settings('project'))}
                                iconOnly
                                sideActionRight
                            >
                                <IconGear className="text-tertiary" />
                            </ButtonPrimitive>
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
                            <ButtonPrimitive menuItem data-attr="new-project-button">
                                <IconPlusSmall className="text-tertiary" />
                                New project
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}
                </div>
            </DropdownMenuContent>
        </DropdownMenu>
    ) : null
}
