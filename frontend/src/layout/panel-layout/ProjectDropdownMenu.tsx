import { IconCheck, IconGear, IconPlusSmall } from '@posthog/icons'
import { LemonSnack, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
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
import { getProjectSwitchTargetUrl } from 'lib/utils/router-utils'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { cn } from 'lib/utils/css-classes'
import { globalModalsLogic } from '~/layout/GlobalModals'
import { AvailableFeature, TeamBasicType } from '~/types'

export function ProjectName({ team }: { team: TeamBasicType }): JSX.Element {
    return (
        <div className="flex items-center max-w-full">
            <span className="truncate">{team.name}</span>
            {team.is_demo ? <LemonSnack className="ml-2 text-xs shrink-0">Demo</LemonSnack> : null}
        </div>
    )
}

export function ProjectDropdownMenu({
    buttonProps = { className: 'font-semibold' },
}: {
    buttonProps?: ButtonPrimitiveProps
}): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateProjectModal } = useActions(globalModalsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization, projectCreationForbiddenReason } = useValues(organizationLogic)

    return isAuthenticatedTeam(currentTeam) ? (
        <PopoverPrimitive>
            <PopoverPrimitiveTrigger asChild>
                <ButtonPrimitive
                    data-attr="tree-navbar-project-dropdown-button"
                    size="sm"
                    {...buttonProps}
                    className={cn('flex-1 max-w-fit min-w-[40px]', buttonProps.className)}
                >
                    <span className="truncate">{currentTeam.name ?? 'Project'}</span>
                    <DropdownMenuOpenIndicator />
                </ButtonPrimitive>
            </PopoverPrimitiveTrigger>
            <PopoverPrimitiveContent
                align="start"
                className="w-[var(--project-panel-inner-width)] max-w-[var(--project-panel-inner-width)]"
            >
                <Combobox>
                    <Combobox.Search placeholder="Filter projects..." />
                    <Combobox.Content>
                        <Label intent="menu" className="px-2">
                            Projects
                        </Label>
                        <div className="-mx-1 my-1 h-px bg-border-primary shrink-0" />

                        <Combobox.Empty>No projects found</Combobox.Empty>

                        <Combobox.Group value={[currentTeam.name]}>
                            <ButtonGroupPrimitive fullWidth>
                                <Combobox.Item asChild>
                                    <ButtonPrimitive
                                        menuItem
                                        active
                                        hasSideActionRight
                                        tooltip={`Current project: ${currentTeam.name}`}
                                        tooltipPlacement="right"
                                        data-attr="tree-navbar-project-dropdown-current-project-button"
                                        className="pr-12"
                                    >
                                        <IconCheck className="text-tertiary" />
                                        <ProjectName team={currentTeam} />
                                    </ButtonPrimitive>
                                </Combobox.Item>

                                <Combobox.Item asChild>
                                    <Link
                                        buttonProps={{
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
                                </Combobox.Item>
                            </ButtonGroupPrimitive>
                        </Combobox.Group>

                        {currentOrganization?.teams &&
                            currentOrganization.teams
                                .filter((team) => team.id !== currentTeam?.id)
                                .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                                .map((team) => {
                                    const relativeOtherProjectPath = getProjectSwitchTargetUrl(
                                        location.pathname,
                                        team.id,
                                        currentTeam?.project_id,
                                        team.project_id
                                    )

                                    return (
                                        <Combobox.Group value={[team.name]} key={team.id}>
                                            <ButtonGroupPrimitive menuItem fullWidth>
                                                <Combobox.Item asChild>
                                                    <Link
                                                        buttonProps={{
                                                            menuItem: true,
                                                            hasSideActionRight: true,
                                                            className: 'pr-12',
                                                        }}
                                                        tooltip={`Switch to project: ${team.name}`}
                                                        tooltipPlacement="right"
                                                        to={relativeOtherProjectPath}
                                                        data-attr="tree-navbar-project-dropdown-other-project-button"
                                                    >
                                                        <IconBlank />
                                                        <ProjectName team={team} />
                                                    </Link>
                                                </Combobox.Item>

                                                <Combobox.Item asChild>
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
                                                </Combobox.Item>
                                            </ButtonGroupPrimitive>
                                        </Combobox.Group>
                                    )
                                })}

                        {preflight?.can_create_org && (
                            <Combobox.Item
                                asChild
                                onClick={() =>
                                    guardAvailableFeature(
                                        AvailableFeature.ORGANIZATIONS_PROJECTS,
                                        showCreateProjectModal,
                                        {
                                            currentUsage: currentOrganization?.teams?.length,
                                        }
                                    )
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
                        )}
                    </Combobox.Content>
                </Combobox>
            </PopoverPrimitiveContent>
        </PopoverPrimitive>
    ) : null
}
