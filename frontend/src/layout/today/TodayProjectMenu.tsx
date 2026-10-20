import { useActions, useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { IconChevronDown, IconGear, IconPlusSmall, IconSearch } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    ComboboxListFooter,
    ComboboxTrigger,
    InputGroupAddon,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { getProjectSwitchTargetUrl } from 'lib/utils/kea-router'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { globalModalsLogic } from '~/layout/globalModalsLogic'
import { AvailableFeature } from '~/types'

interface ProjectGroup {
    value: string
    items: string[]
}

/** The project switcher shortcut opens this menu too. */
export function TodayProjectMenu(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganizationProjectCount, projectCreationForbiddenReason } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateProjectModal } = useActions(globalModalsLogic)
    const { isProjectSwitcherOpen, projectSearchValue, projectGroups } = useValues(newAccountMenuLogic)
    const { openProjectSwitcher, closeProjectSwitcher, setProjectSearchValue } = useActions(newAccountMenuLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)

    const { groups, teamById } = useMemo(() => {
        const teams = new Map(projectGroups.flatMap((group) => group.projects.map((p) => [String(p.id), p.team])))
        return {
            groups: projectGroups.map(
                (group): ProjectGroup => ({
                    value: group.name ?? 'Projects',
                    items: group.projects.map((p) => String(p.id)),
                })
            ),
            teamById: teams,
        }
    }, [projectGroups])

    const canCreateProject = preflight?.can_create_org !== false && !projectCreationForbiddenReason
    const newProjectButton = (
        <Button
            size="row"
            left
            disabled={!canCreateProject}
            focusableWhenDisabled
            onClick={() =>
                guardAvailableFeature(
                    AvailableFeature.ORGANIZATIONS_PROJECTS,
                    () => {
                        closeProjectSwitcher()
                        showCreateProjectModal()
                    },
                    { currentUsage: currentOrganizationProjectCount }
                )
            }
            data-attr="today-top-bar-new-project"
        >
            <IconPlusSmall />
            New project
        </Button>
    )

    return (
        <Combobox
            items={groups}
            value={currentTeam ? String(currentTeam.id) : null}
            inputValue={projectSearchValue}
            open={isProjectSwitcherOpen}
            autoHighlight
            highlightItemOnHover
            itemToStringLabel={(id: string | null) => (id ? (teamById.get(id)?.name ?? '') : '')}
            onInputValueChange={(value: string) => setProjectSearchValue(value)}
            onOpenChange={(open: boolean) => (open ? openProjectSwitcher() : closeProjectSwitcher())}
            onValueChange={(id: string | null) => {
                const team = id ? teamById.get(id) : null
                if (!team || team.id === currentTeam?.id) {
                    return
                }
                closeProjectSwitcher()
                window.location.href = getProjectSwitchTargetUrl(
                    location.pathname,
                    team.id,
                    currentTeam?.project_id,
                    team.project_id
                )
            }}
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={
                    <Button className="min-w-0 gap-1.5 px-1.5" data-attr="today-top-bar-project-menu">
                        <span className="max-w-48 min-w-0 truncate">{currentTeam?.name ?? 'Select project'}</span>
                        <IconChevronDown className="size-3 shrink-0 text-muted-foreground" />
                    </Button>
                }
            />
            <ComboboxContent
                anchor={triggerRef}
                align="start"
                className="w-64 [&_[data-slot=combobox-input-group-wrapper]]:border-b-0"
            >
                <ComboboxInput placeholder="Search projects" autoFocus showTrigger={false} className="h-7">
                    <InputGroupAddon align="inline-start">
                        <IconSearch className="size-3" />
                    </InputGroupAddon>
                </ComboboxInput>
                <ComboboxEmpty>No projects match your search</ComboboxEmpty>
                <ComboboxList>
                    {(group: ProjectGroup) => (
                        <ComboboxGroup key={group.value} items={group.items}>
                            <ComboboxLabel>{group.value}</ComboboxLabel>
                            <ComboboxCollection>
                                {(id: string) => (
                                    <ComboboxItem key={id} value={id} data-attr="today-top-bar-project-item">
                                        <span className="min-w-0 truncate">{teamById.get(id)?.name}</span>
                                    </ComboboxItem>
                                )}
                            </ComboboxCollection>
                        </ComboboxGroup>
                    )}
                </ComboboxList>
                <ComboboxListFooter className="mx-0 mt-0 flex flex-col gap-0.5 bg-transparent before:hidden">
                    {currentTeam && (
                        <Button
                            size="row"
                            left
                            render={<LinkPrimitive to={urls.project(currentTeam.id, urls.settings('project'))} />}
                            onClick={() => closeProjectSwitcher()}
                            data-attr="today-top-bar-project-settings"
                        >
                            <IconGear />
                            Project settings
                        </Button>
                    )}
                    {preflight?.can_create_org &&
                        (canCreateProject ? (
                            newProjectButton
                        ) : (
                            <Tooltip>
                                <TooltipTrigger render={newProjectButton} />
                                <TooltipContent>
                                    {projectCreationForbiddenReason || "You don't have permission to create a project"}
                                </TooltipContent>
                            </Tooltip>
                        ))}
                </ComboboxListFooter>
            </ComboboxContent>
        </Combobox>
    )
}
