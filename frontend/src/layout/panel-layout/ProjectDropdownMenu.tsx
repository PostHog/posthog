import { IconChevronRight, IconFolderOpen, IconGear, IconPlusSmall } from '@posthog/icons'
import { LemonSnack } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { Button } from 'lib/ui/Button/Button'
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
            <Button.Root menuItem to={relativeOtherProjectPath}>
                <Button.Label>
                    <ProjectName team={team} />
                </Button.Label>
                <Button.Icon
                    isTrigger
                    isTriggerRight
                    onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        e.nativeEvent.stopImmediatePropagation()
                        router.actions.push(urls.project(team.id, urls.settings()))
                    }}
                >
                    <IconGear />
                </Button.Icon>
            </Button.Root>
        </DropdownMenuItem>
    )
}

export function ProjectDropdownMenu(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { closeAccountPopover } = useActions(navigationLogic)
    const { showCreateProjectModal } = useActions(globalModalsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { push } = useActions(router)
    const { currentOrganization } = useValues(organizationLogic)

    return isAuthenticatedTeam(currentTeam) ? (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button.Root>
                    <Button.Icon>
                        <IconFolderOpen className="text-tertiary" />
                    </Button.Icon>
                    <Button.Label>Project</Button.Label>
                    <Button.Icon size="sm">
                        <IconChevronRight className="text-secondary rotate-90 group-data-[state=open]/button-root:rotate-270 transition-transform duration-200 prefers-reduced-motion:transition-none" />
                    </Button.Icon>
                </Button.Root>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="start">
                <DropdownMenuLabel>Projects</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <div className="flex flex-col gap-px">
                    <DropdownMenuItem asChild>
                        <Button.Root menuItem active>
                            <Button.Label menuItem>
                                <ProjectName team={currentTeam} />
                            </Button.Label>
                            <Button.Icon onClick={() => push(urls.settings('project'))} isTrigger isTriggerRight>
                                <IconGear className="text-tertiary" />
                            </Button.Icon>
                        </Button.Root>
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
                            <Button.Root menuItem data-attr="new-project-button">
                                <Button.Icon>
                                    <IconPlusSmall className="text-tertiary" />
                                </Button.Icon>
                                <Button.Label menuItem>New project</Button.Label>
                            </Button.Root>
                        </DropdownMenuItem>
                    )}
                </div>
            </DropdownMenuContent>
        </DropdownMenu>
    ) : null
}
