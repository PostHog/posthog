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
import { forwardRef, useMemo } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxFooter, ComboboxGroup, ComboboxItem, ComboboxSearch } from 'lib/ui/Combobox/Combobox'
import { PopoverPrimitive, PopoverPrimitiveContent, PopoverPrimitiveTrigger } from 'lib/ui/PopoverPrimitive/PopoverPrimitive'

import { globalModalsLogic } from '~/layout/GlobalModals'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { AvailableFeature, TeamBasicType } from '~/types'
import { Label } from 'lib/ui/Label/Label'

export function ProjectName({ team }: { team: TeamBasicType }): JSX.Element {
    return (
        <div className="flex items-center max-w-full">
            <span className="truncate">{team.name}</span>
            {team.is_demo ? <LemonSnack className="ml-2 text-xs shrink-0">Demo</LemonSnack> : null}
        </div>
    )
}

// const OtherProjectButton = forwardRef<HTMLAnchorElement, { children: ReactNode, team: TeamBasicType }>(({ children, team }, ref): JSX.Element => {
//     const { location } = useValues(router)
//     const { currentTeam } = useValues(teamLogic)

//     const relativeOtherProjectPath = useMemo(() => {
//         return getProjectSwitchTargetUrl(location.pathname, team.id, currentTeam?.project_id, team.project_id)
//     }, [location.pathname, team.id, team.project_id, currentTeam?.project_id])

//     return (
//         <ButtonGroupPrimitive menuItem fullWidth>
//             <Link
//                 ref={ref}
//                 buttonProps={{
//                     menuItem: true,
//                     hasSideActionRight: true,
//                 }}
//                 tooltip={`Switch to project: ${team.name}`}
//                 tooltipPlacement="right"
//                 to={relativeOtherProjectPath}
//                 data-attr="tree-navbar-project-dropdown-other-project-button"
//             >
//                 <ProjectName team={team} />
//             </Link> 

//             <Link
//                 buttonProps={{
//                     iconOnly: true,
//                     isSideActionRight: true,
//                 }}
//                 tooltip={`View settings for project: ${team.name}`}
//                 tooltipPlacement="right"
//                 to={urls.project(team.id, urls.settings('project'))}
//                 data-attr="tree-navbar-project-dropdown-other-project-settings-button"
//             >
//                 <IconGear />
//             </Link>
//         </ButtonGroupPrimitive>
//     )
// })

export function ProjectDropdownMenu(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { closeAccountPopover } = useActions(navigationLogic)
    const { showCreateProjectModal } = useActions(globalModalsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)

    return isAuthenticatedTeam(currentTeam) ? (
        <>
            <PopoverPrimitive >
                <PopoverPrimitiveTrigger asChild>
                    <ButtonPrimitive
                        data-attr="tree-navbar-project-dropdown-button"
                    >
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
                </PopoverPrimitiveTrigger>
                <PopoverPrimitiveContent
                    align="start"
                    className={"min-w-[200px] max-w-[var(--project-panel-inner-width)]"}
                >
                    <Combobox>
                        <ComboboxSearch placeholder="Search projects..." autoFocus />
                        <ComboboxContent className='max-h-[300px]'>
                            <Label intent="menu" className='px-2'>Projects</Label>
                            <div className="-mx-1 my-1 h-px bg-border-primary" />

                            <ComboboxEmpty>No projects found</ComboboxEmpty>

                            <ComboboxGroup>
                                    <ButtonGroupPrimitive fullWidth disabled>
                                <ComboboxItem asChild filterValue={currentTeam.name}>
                                        <ButtonPrimitive
                                            menuItem
                                            active
                                            hasSideActionRight
                                            tooltip={`Current project: ${currentTeam.name}`}
                                        tooltipPlacement="right"
                                        disabled
                                        data-attr="tree-navbar-project-dropdown-current-project-button"
                                    >
                                        <ProjectName team={currentTeam} />
                                    </ButtonPrimitive>
                                    </ComboboxItem>
                                    <Link
                                        buttonProps={{
                                            active: true,
                                            iconOnly: true,
                                            isSideActionRight: true,
                                        }}
                                        tooltip={`View settings for project: ${currentTeam.name}`}
                                        tooltipPlacement="right"
                                        to={urls.project(currentTeam.id, urls.settings('project'))}
                                        data-attr="tree-navbar-project-dropdown-current-project-settings-button"
                                    >
                                        <IconGear className="text-tertiary" />
                                    </Link>
                                </ButtonGroupPrimitive>
                            </ComboboxGroup>

                            {currentOrganization?.teams &&
                                currentOrganization.teams
                                    .filter((team) => team.id !== currentTeam?.id)
                                    .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                                    .map((team) => {
                                        const relativeOtherProjectPath = getProjectSwitchTargetUrl(location.pathname, team.id, currentTeam?.project_id, team.project_id)

                                        return <ComboboxGroup>
                                            <ButtonGroupPrimitive menuItem fullWidth>
                                            <ComboboxItem asChild filterValue={team.name}>
                                                <Link
                                                    buttonProps={{
                                                        menuItem: true,
                                                        hasSideActionRight: true,
                                                    }}
                                                    tooltip={`Switch to project: ${team.name}`}
                                                    tooltipPlacement="right"
                                                    to={relativeOtherProjectPath}
                                                    data-attr="tree-navbar-project-dropdown-other-project-button"
                                                >
                                                    <ProjectName team={team} />
                                                </Link>
                                            </ComboboxItem>

                                            <Link
                                                buttonProps={{
                                                    iconOnly: true,
                                                    isSideActionRight: true,
                                                }}
                                                tooltip={`View settings for project: ${team.name}`}
                                                tooltipPlacement="right"
                                                to={urls.project(team.id, urls.settings('project'))}
                                                data-attr="tree-navbar-project-dropdown-other-project-settings-button"
                                            >
                                                <IconGear />
                                            </Link>
                                        </ButtonGroupPrimitive>
                                        </ComboboxGroup>
                                    })}

                        </ComboboxContent>

                            {preflight?.can_create_org && (
                        <ComboboxFooter>
                                <ComboboxItem
                                asChild
                                onClick={() =>
                                    guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, () => {
                                        closeAccountPopover()
                                        showCreateProjectModal()
                                    })
                                }
                                alwaysVisible
                                className="sticky bottom-0"
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
                                </ComboboxItem>
                            </ComboboxFooter>
                            )}
                    </Combobox>
                </PopoverPrimitiveContent>
            </PopoverPrimitive>

            {/* <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive data-attr="tree-navbar-project-dropdown-button">
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
                                data-attr="tree-navbar-project-dropdown-current-project-button"
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
                                data-attr="tree-navbar-project-dropdown-current-project-settings-button"
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
            </DropdownMenu> */}
        </>
    ) : null
}
