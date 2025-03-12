import { IconChevronRight, IconFolderOpen, IconGear, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonSnack } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { IconWrapper } from 'lib/ui/IconWrapper/IconWrapper'
import { cn } from 'lib/utils/css-classes'
import { getProjectSwitchTargetUrl } from 'lib/utils/router-utils'
import { useMemo, useState } from 'react'
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
        <LemonButton
            to={relativeOtherProjectPath}
            sideAction={{
                icon: (
                    <IconWrapper>
                        <IconGear />
                    </IconWrapper>
                ),
                tooltip: `Go to ${team.name} settings`,
                to: urls.project(team.id, urls.settings()),
            }}
            title={`Switch to project ${team.name}`}
            fullWidth
        >
            <ProjectName team={team} />
        </LemonButton>
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

    const [isDropdownOpen, setIsDropdownOpen] = useState(false)

    return isAuthenticatedTeam(currentTeam) ? (
        <DropdownMenu
            onOpenChange={(open) => {
                setIsDropdownOpen(open)
            }}
        >
            <DropdownMenuTrigger asChild>
                <LemonButton
                    icon={
                        <IconWrapper>
                            <IconFolderOpen />
                        </IconWrapper>
                    }
                    size="small"
                    className="hover:bg-fill-highlight-100"
                    sideIcon={
                        <IconWrapper
                            size="sm"
                            className={cn(
                                'transition-transform duration-200 prefers-reduced-motion:transition-none',
                                isDropdownOpen ? 'rotate-270' : 'rotate-90'
                            )}
                        >
                            <IconChevronRight />
                        </IconWrapper>
                    }
                >
                    <span>Project</span>
                </LemonButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="start">
                <DropdownMenuLabel>Projects</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <LemonButton
                    active
                    sideAction={{
                        icon: (
                            <IconWrapper size="sm">
                                <IconGear />
                            </IconWrapper>
                        ),
                        tooltip: `Go to ${currentTeam?.name} settings`,
                        onClick: () => {
                            push(urls.settings('project'))
                        },
                    }}
                    title={`Switch to project ${currentTeam.name}`}
                    fullWidth
                >
                    <ProjectName team={currentTeam} />
                </LemonButton>
                {currentOrganization?.teams &&
                    currentOrganization.teams
                        .filter((team) => team.id !== currentTeam?.id)
                        .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                        .map((team) => <OtherProjectButton key={team.id} team={team} />)}
                {preflight?.can_create_org && (
                    <DropdownMenuItem asChild>
                        <LemonButton
                            icon={
                                <IconWrapper>
                                    <IconPlusSmall />
                                </IconWrapper>
                            }
                            onClick={() =>
                                guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, () => {
                                    closeAccountPopover()
                                    showCreateProjectModal()
                                })
                            }
                            fullWidth
                            size="small"
                            data-attr="new-organization-button"
                        >
                            New project
                        </LemonButton>
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    ) : null
}
