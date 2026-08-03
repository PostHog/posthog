import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconChevronRight, IconFolderOpen, IconPencil, IconPin, IconPlus, IconTrash } from '@posthog/icons'
import { LemonDialog, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
import { FileSystemEntry, FileSystemIconType, SidebarCustomGroup } from '~/queries/schema/schema-general'

import { SectionTrigger } from './Nav'

function entryName(entry: FileSystemEntry): string {
    const lastPart = splitPath(entry.path).pop()
    return unescapePath(lastPart ?? entry.path)
}

function promptForGroupName(title: string, initialLabel: string, onSubmit: (label: string) => void): void {
    LemonDialog.openForm({
        title,
        initialValues: { label: initialLabel },
        content: (
            <LemonField name="label">
                <LemonInput placeholder="Group name" autoFocus data-attr="sidebar-group-name-input" />
            </LemonField>
        ),
        errors: {
            label: (label) => (!label?.trim() ? 'Please enter a name' : undefined),
        },
        onSubmit: ({ label }) => onSubmit(label.trim()),
    })
}

function PinnedRow({ entry, group }: { entry: FileSystemEntry; group?: SidebarCustomGroup }): JSX.Element {
    const { pathname } = useValues(panelLayoutLogic)
    const { sidebarGroups } = useValues(uiCustomizationLogic)
    const { setShortcutGroup, createSidebarGroup } = useActions(uiCustomizationLogic)
    const { deleteShortcut } = useActions(projectTreeDataLogic)

    const unpin = (): void => {
        // Drop the group membership too, so no stale shortcut id lingers in the stored config.
        if (group) {
            setShortcutGroup(entry.id, null)
        }
        deleteShortcut(entry.id)
    }

    const name = entryName(entry)
    const isActive = entry.href ? removeProjectIdIfPresent(pathname) === entry.href : false

    return (
        <ContextMenu>
            <ContextMenuTrigger asChild>
                <span className="block w-full">
                    <Tooltip title={name} placement="right">
                        <Link
                            to={entry.href}
                            buttonProps={{ menuItem: true, active: isActive, className: 'group -outline-offset-2' }}
                            data-attr={`nav-pinned-item-${entry.id}`}
                            onClick={() => posthog.capture('nav pinned item clicked', { type: entry.type })}
                        >
                            <span className="flex size-4 text-secondary items-center justify-center">
                                {iconForType(entry.type as FileSystemIconType)}
                            </span>
                            <span className="flex-1 truncate text-left text-secondary group-hover:text-primary">
                                {name}
                            </span>
                        </Link>
                    </Tooltip>
                </span>
            </ContextMenuTrigger>
            <ContextMenuContent loop className="max-w-[250px]">
                <ContextMenuGroup>
                    <ContextMenuSub>
                        <ContextMenuSubTrigger asChild>
                            <ButtonPrimitive menuItem>
                                <IconFolderOpen className="size-4 text-tertiary" />
                                Move to group
                                <IconChevronRight className="ml-auto size-3 text-secondary" />
                            </ButtonPrimitive>
                        </ContextMenuSubTrigger>
                        <ContextMenuSubContent>
                            <ContextMenuGroup>
                                {sidebarGroups.map((existing) => (
                                    <ContextMenuItem key={existing.id} asChild disabled={existing.id === group?.id}>
                                        <ButtonPrimitive
                                            menuItem
                                            disabled={existing.id === group?.id}
                                            onClick={() => setShortcutGroup(entry.id, existing.id)}
                                        >
                                            {existing.label}
                                        </ButtonPrimitive>
                                    </ContextMenuItem>
                                ))}
                                {group && (
                                    <ContextMenuItem asChild>
                                        <ButtonPrimitive menuItem onClick={() => setShortcutGroup(entry.id, null)}>
                                            No group
                                        </ButtonPrimitive>
                                    </ContextMenuItem>
                                )}
                                {sidebarGroups.length > 0 && <ContextMenuSeparator />}
                                <ContextMenuItem asChild>
                                    <ButtonPrimitive
                                        menuItem
                                        onClick={() =>
                                            promptForGroupName('New group', '', (label) =>
                                                createSidebarGroup(label, entry.id)
                                            )
                                        }
                                    >
                                        <IconPlus className="size-4 text-tertiary" />
                                        New group
                                    </ButtonPrimitive>
                                </ContextMenuItem>
                            </ContextMenuGroup>
                        </ContextMenuSubContent>
                    </ContextMenuSub>
                    <ContextMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={unpin}>
                            <IconPin className="size-4 text-tertiary" />
                            Unpin from sidebar
                        </ButtonPrimitive>
                    </ContextMenuItem>
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}

function GroupSection({ group, entries }: { group: SidebarCustomGroup; entries: FileSystemEntry[] }): JSX.Element {
    const { expandedNavSections } = useValues(panelLayoutLogic)
    const { setNavSectionExpanded } = useActions(panelLayoutLogic)
    const { renameSidebarGroup, deleteSidebarGroup } = useActions(uiCustomizationLogic)

    const sectionKey = `pinned-group-${group.id}`

    return (
        <Collapsible
            open={expandedNavSections[sectionKey] ?? true}
            onOpenChange={(open) => setNavSectionExpanded(sectionKey, open)}
            className="mt-2"
            data-attr="nav-section-pinned-group"
        >
            <ContextMenu>
                <ContextMenuTrigger asChild>
                    <span className="block w-full">
                        <SectionTrigger icon={<IconFolderOpen />} label={group.label} isCollapsed={false} />
                    </span>
                </ContextMenuTrigger>
                <ContextMenuContent loop className="max-w-[250px]">
                    <ContextMenuGroup>
                        <ContextMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                onClick={() =>
                                    promptForGroupName('Rename group', group.label, (label) =>
                                        renameSidebarGroup(group.id, label)
                                    )
                                }
                            >
                                <IconPencil className="size-4 text-tertiary" />
                                Rename group
                            </ButtonPrimitive>
                        </ContextMenuItem>
                        <ContextMenuItem asChild>
                            <ButtonPrimitive menuItem onClick={() => deleteSidebarGroup(group.id)}>
                                <IconTrash className="size-4 text-tertiary" />
                                Delete group
                            </ButtonPrimitive>
                        </ContextMenuItem>
                    </ContextMenuGroup>
                </ContextMenuContent>
            </ContextMenu>
            <Collapsible.Panel className="pl-2">
                {entries.map((entry) => (
                    <PinnedRow key={entry.id} entry={entry} group={group} />
                ))}
            </Collapsible.Panel>
        </Collapsible>
    )
}

/**
 * Items pinned to the sidebar (file system shortcuts: dashboards, insights, folders, and so on),
 * rendered directly in the navbar so a pinned item is one click away, plus the user's custom groups.
 * Deleting a group never deletes the pins inside it: unreferenced pins simply return to the flat list.
 */
export function NavPinned({ flattened }: { flattened: boolean }): JSX.Element | null {
    const { shortcutData } = useValues(projectTreeDataLogic)
    const { sidebarGroups } = useValues(uiCustomizationLogic)
    const { expandedNavSections } = useValues(panelLayoutLogic)
    const { setNavSectionExpanded } = useActions(panelLayoutLogic)

    const entryById = new Map(shortcutData.map((entry) => [entry.id, entry]))
    const groupedIds = new Set(sidebarGroups.flatMap((group) => group.items ?? []))
    const ungrouped = shortcutData.filter((entry) => !groupedIds.has(entry.id))
    // Groups whose ids resolve to no shortcut in this project don't render: shortcuts are
    // project-scoped while groups live on the user, so another project's groups would otherwise
    // show up everywhere as permanently empty sections.
    const groups = sidebarGroups
        .map((group) => ({
            group,
            entries: (group.items ?? [])
                .map((id) => entryById.get(id))
                .filter((entry): entry is FileSystemEntry => !!entry),
        }))
        .filter(({ entries }) => entries.length > 0)

    if (shortcutData.length === 0 && sidebarGroups.length === 0) {
        return null
    }

    const ungroupedRows = ungrouped.map((entry) => <PinnedRow key={entry.id} entry={entry} />)

    if (flattened) {
        return (
            <>
                <div className="flex flex-col gap-px">{ungroupedRows}</div>
                {groups.map(({ group, entries }) => (
                    <GroupSection key={group.id} group={group} entries={entries} />
                ))}
            </>
        )
    }

    return (
        <>
            <Collapsible
                open={expandedNavSections.pinned ?? true}
                onOpenChange={(open) => {
                    posthog.capture('nav section toggled', { section: 'pinned', is_open: open })
                    setNavSectionExpanded('pinned', open)
                }}
                className="mt-2"
                data-attr="nav-section-pinned"
            >
                <SectionTrigger icon={<IconPin />} label="Pinned" isCollapsed={false} />
                <Collapsible.Panel className="pl-2">
                    {ungroupedRows.length === 0 ? (
                        <span className="text-xs text-tertiary px-2 py-1">Nothing pinned yet</span>
                    ) : (
                        ungroupedRows
                    )}
                </Collapsible.Panel>
            </Collapsible>
            {groups.map(({ group, entries }) => (
                <GroupSection key={group.id} group={group} entries={entries} />
            ))}
        </>
    )
}
