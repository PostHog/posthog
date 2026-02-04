import { Combobox } from '@base-ui/react/combobox'
import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef, useState } from 'react'

import { IconCheck, IconPlusSmall, IconSearch, IconX } from '@posthog/icons'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { getProjectSwitchTargetUrl } from 'lib/utils/router-utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'

import { globalModalsLogic } from '~/layout/GlobalModals'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { AvailableFeature, TeamBasicType } from '~/types'

import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { ProjectName } from './ProjectMenu'
import { newAccountMenuLogic } from './newAccountMenuLogic'

interface ProjectListItem {
    type: 'project'
    id: number
    team: TeamBasicType
    isCurrent: boolean
}

interface CreateProjectItem {
    type: 'create'
    id: 'create-new-project'
    label: string
}

type ListItem = ProjectListItem | CreateProjectItem

export function ProjectSwitcher(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateProjectModal } = useActions(globalModalsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization, projectCreationForbiddenReason } = useValues(organizationLogic)
    const { closeProjectSwitcher } = useActions(newAccountMenuLogic)

    const [searchValue, setSearchValue] = useState('')
    const inputRef = useRef<HTMLInputElement>(null!)

    const allProjectItems: ProjectListItem[] = useMemo(() => {
        const items: ProjectListItem[] = []

        if (currentOrganization?.teams) {
            for (const team of currentOrganization.teams) {
                items.push({
                    type: 'project',
                    id: team.id,
                    team,
                    isCurrent: team.id === currentTeam?.id,
                })
            }
        }

        return items
    }, [currentOrganization?.teams, currentTeam?.id])

    const filteredItems = useMemo(() => {
        const searchLower = searchValue.trim().toLowerCase()

        // Filter project items
        const filteredProjects = searchLower
            ? allProjectItems.filter((item) => item.team.name.toLowerCase().includes(searchLower))
            : allProjectItems

        // Create the "create" item - show different label based on search
        const createItem: CreateProjectItem = {
            type: 'create',
            id: 'create-new-project',
            label: 'New project',
            // TODO: Uncomment this when we have a way to create projects with a name
            // label: searchValue.trim() ? `Create '${searchValue.trim()}'` : 'New project',
        }

        return [...filteredProjects, createItem] as ListItem[]
    }, [allProjectItems, searchValue])

    const currentProject = filteredItems.find((p): p is ProjectListItem => p.type === 'project' && p.isCurrent)
    const otherProjects = filteredItems
        .filter((p): p is ProjectListItem => p.type === 'project' && !p.isCurrent)
        .sort((a, b) => a.team.name.localeCompare(b.team.name))
    const createItem = filteredItems.find((p): p is CreateProjectItem => p.type === 'create')

    const handleItemClick = useCallback(
        (item: ListItem) => {
            if (item.type === 'create') {
                guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, showCreateProjectModal, {
                    currentUsage: currentOrganization?.teams?.length,
                })
                closeProjectSwitcher()
            } else if (!item.isCurrent) {
                const targetUrl = getProjectSwitchTargetUrl(
                    location.pathname,
                    item.team.id,
                    currentTeam?.project_id,
                    item.team.project_id
                )
                closeProjectSwitcher()
                window.location.href = targetUrl
            }
        },
        [
            currentTeam?.project_id,
            closeProjectSwitcher,
            guardAvailableFeature,
            showCreateProjectModal,
            currentOrganization?.teams?.length,
        ]
    )

    const getItemString = useCallback((item: ListItem | null): string => {
        if (!item) {
            return ''
        }
        if (item.type === 'create') {
            return item.label
        }
        return item.team.name
    }, [])

    const canCreateProject = preflight?.can_create_org !== false && !projectCreationForbiddenReason

    if (!isAuthenticatedTeam(currentTeam)) {
        return null
    }

    return (
        <Combobox.Root
            items={filteredItems}
            filter={null}
            itemToStringValue={getItemString}
            inline
            defaultOpen
            autoHighlight
        >
            <div className="flex flex-col overflow-hidden">
                {/* Search Input */}
                <div className="p-2 border-b border-primary">
                    <label className="group input-like flex gap-1 items-center relative w-full bg-fill-input border border-primary focus-within:ring-primary py-1 px-2">
                        <Combobox.Icon
                            render={
                                <IconSearch className="size-4 shrink-0 text-tertiary group-focus-within:text-primary" />
                            }
                        />
                        <Combobox.Input
                            ref={inputRef}
                            value={searchValue}
                            onChange={(e) => setSearchValue(e.target.value)}
                            aria-label="Search projects"
                            placeholder="Search projects..."
                            className="w-full px-1 py-1 text-sm focus:outline-none border-transparent"
                            autoFocus
                        />
                        {searchValue && (
                            <Combobox.Clear
                                render={
                                    <ButtonPrimitive
                                        iconOnly
                                        size="sm"
                                        onClick={() => setSearchValue('')}
                                        aria-label="Clear search"
                                        className="-mr-1"
                                    >
                                        <IconX className="size-4 text-tertiary" />
                                    </ButtonPrimitive>
                                }
                            />
                        )}
                    </label>
                </div>

                {/* Results */}
                <ScrollableShadows
                    direction="vertical"
                    styledScrollbars
                    className="flex-1 overflow-y-auto max-h-[400px]"
                >
                    <Combobox.List className="flex flex-col gap-px p-2" tabIndex={-1}>
                        {/* Current Project */}
                        {currentProject && (
                            <Combobox.Group items={[currentProject]}>
                                <Combobox.Collection>
                                    {(item: ProjectListItem) => (
                                        <Combobox.Item
                                            key={item.id}
                                            value={item}
                                            onClick={() => handleItemClick(item)}
                                            disabled
                                            render={(props) => (
                                                <ButtonPrimitive
                                                    {...props}
                                                    menuItem
                                                    active
                                                    className="flex-1"
                                                    tabIndex={-1}
                                                    disabled={true}
                                                    data-disabled="true"
                                                >
                                                    <IconCheck className="text-tertiary" />
                                                    <ProjectName team={item.team} />
                                                </ButtonPrimitive>
                                            )}
                                        />
                                    )}
                                </Combobox.Collection>
                            </Combobox.Group>
                        )}

                        {/* Other Projects */}
                        {otherProjects.length > 0 && (
                            <Combobox.Group items={otherProjects}>
                                <Combobox.Collection>
                                    {(item: ProjectListItem) => (
                                        <Combobox.Item
                                            key={item.id}
                                            value={item}
                                            onClick={() => handleItemClick(item)}
                                            render={(props) => (
                                                <ButtonPrimitive
                                                    {...props}
                                                    menuItem
                                                    className="flex-1"
                                                    tabIndex={-1}
                                                    hasSideActionRight
                                                >
                                                    <IconBlank />
                                                    <ProjectName team={item.team} />
                                                </ButtonPrimitive>
                                            )}
                                        />
                                    )}
                                </Combobox.Collection>
                            </Combobox.Group>
                        )}

                        {/* Create New Project */}
                        {createItem && (
                            <Combobox.Group items={[createItem]}>
                                <Combobox.Collection>
                                    {(item: CreateProjectItem) => (
                                        <Combobox.Item
                                            key={item.id}
                                            value={item}
                                            onClick={() => handleItemClick(item)}
                                            render={(props) => (
                                                <ButtonPrimitive
                                                    {...props}
                                                    menuItem
                                                    fullWidth
                                                    tabIndex={-1}
                                                    disabled={!canCreateProject}
                                                    tooltip={
                                                        !canCreateProject
                                                            ? projectCreationForbiddenReason ||
                                                              'You do not have permission to create a project'
                                                            : undefined
                                                    }
                                                    tooltipPlacement="right"
                                                >
                                                    <IconPlusSmall className="text-tertiary" />
                                                    <span className="truncate">{item.label}</span>
                                                </ButtonPrimitive>
                                            )}
                                        />
                                    )}
                                </Combobox.Collection>
                            </Combobox.Group>
                        )}
                    </Combobox.List>
                </ScrollableShadows>

                {/* Footer */}
                <div className="menu-legend border-t border-primary p-1">
                    <div className="px-2 py-1 text-xxs text-tertiary font-medium flex items-center gap-2">
                        <span>
                            <KeyboardShortcut arrowup arrowdown preserveOrder /> navigate
                        </span>
                        <span>
                            <KeyboardShortcut enter /> select
                        </span>
                        <span>
                            <KeyboardShortcut escape /> close
                        </span>
                    </div>
                </div>
            </div>
        </Combobox.Root>
    )
}
