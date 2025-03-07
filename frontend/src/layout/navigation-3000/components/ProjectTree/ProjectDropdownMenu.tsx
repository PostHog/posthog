import { IconChevronDown, IconGear, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonSnack } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { IconFolderOpen } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
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
                icon: <IconGear className="text-secondary" />,
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
    const { showCreateOrganizationModal } = useActions(globalModalsLogic)
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
                    icon={<IconFolderOpen className="size-5" />}
                    size="small"
                    className="hover:bg-fill-highlight-100"
                >
                    <span>Project</span>
                    <IconChevronDown
                        className={cn(
                            'size-5 transition-transform duration-200 prefers-reduced-motion:transition-none',
                            isDropdownOpen && 'rotate-180'
                        )}
                    />
                </LemonButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="start">
                <DropdownMenuLabel>Projects</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <LemonButton
                    active
                    sideAction={{
                        icon: <IconGear className="text-secondary" />,
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
                            icon={<IconPlusSmall />}
                            onClick={() =>
                                guardAvailableFeature(
                                    AvailableFeature.ORGANIZATIONS_PROJECTS,
                                    () => {
                                        closeAccountPopover()
                                        showCreateOrganizationModal()
                                    },
                                    {
                                        guardOnCloud: false,
                                    }
                                )
                            }
                            fullWidth
                            size="small"
                            data-attr="new-organization-button"
                        >
                            New organization
                        </LemonButton>
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    ) : null
}
