import {
    DndContext,
    DragEndEvent,
    DragOverlay,
    DragStartEvent,
    MouseSensor,
    TouchSensor,
    useDraggable,
    useDroppable,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { CSSProperties, HTMLAttributes, MouseEvent, useCallback, useEffect, useMemo, useState } from 'react'

import { IconChevronRight, IconEllipsis } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenu, ContextMenuContent, ContextMenuGroup, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'
import { ProjectTreeLogicProps, projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import {
    calculateMovePath,
    getItemId,
    joinPath,
    sortFilesAndFolders,
    splitPath,
} from '~/layout/panel-layout/ProjectTree/utils'
import { TreeDataItem } from '~/lib/lemon-ui/LemonTree/LemonTree'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { getNewTabProjectTreeLogicProps, newTabSceneLogic } from '../newTabSceneLogic'

const CHILD_INDENT_PX = 24

type EntryWithProtocol = FileSystemEntry & { protocol?: string }

const convertEntryToTreeDataItem = (entry: EntryWithProtocol): TreeDataItem => {
    const protocol = entry.protocol ?? 'project://'

    return {
        id: getItemId(entry, protocol),
        name: splitPath(entry.path).pop() || entry.path || 'Unnamed entry',
        record: {
            ...entry,
            protocol,
        },
    }
}

interface ExplorerRow {
    entry: FileSystemEntry
    depth: number
    isParentNavigation?: boolean
    navigatesToSearch?: boolean
    isSearchResult?: boolean
}

export function ProjectExplorer({
    tabId,
    listboxRef,
}: {
    tabId: string
    listboxRef: React.RefObject<ListBoxHandle>
}): JSX.Element | null {
    const projectTreeLogicProps = useMemo(() => getNewTabProjectTreeLogicProps(tabId), [tabId])
    const { checkedItems, folders, folderStates, users } = useValues(projectTreeLogic(projectTreeLogicProps))
    const { loadFolder, moveCheckedItems, moveItem } = useActions(projectTreeLogic(projectTreeLogicProps))
    const {
        activeExplorerFolderPath,
        explorerExpandedFolders,
        highlightedExplorerEntryPath,
        search,
        explorerSearchResults,
        explorerSearchResultsLoading,
    } = useValues(newTabSceneLogic({ tabId }))
    const { setActiveExplorerFolderPath, toggleExplorerFolderExpansion, setHighlightedExplorerEntryPath } = useActions(
        newTabSceneLogic({ tabId })
    )
    const hasActiveFolder = activeExplorerFolderPath !== null
    const explorerFolderPath = activeExplorerFolderPath ?? ''
    const mouseSensor = useSensor(MouseSensor, {
        activationConstraint: {
            distance: 10,
        },
    })
    const touchSensor = useSensor(TouchSensor, {
        activationConstraint: {
            delay: 250,
            tolerance: 5,
        },
    })
    const sensors = useSensors(mouseSensor, touchSensor)
    const rootDroppableId = `project://${explorerFolderPath}`
    const { setNodeRef: setRootDropZoneRef, isOver: isOverRoot } = useDroppable({ id: rootDroppableId })
    const [activeDragItem, setActiveDragItem] = useState<TreeDataItem | null>(null)
    const isDragging = !!activeDragItem

    useEffect(() => {
        if (activeExplorerFolderPath === null) {
            return
        }
        if (!folders[activeExplorerFolderPath] && folderStates[activeExplorerFolderPath] !== 'loading') {
            loadFolder(activeExplorerFolderPath)
        }
    }, [activeExplorerFolderPath, folders, folderStates, loadFolder])

    const currentEntries = hasActiveFolder ? folders[explorerFolderPath] || [] : []

    const rows = useMemo(() => {
        const buildRowsRecursive = (entries: FileSystemEntry[], depth: number): ExplorerRow[] => {
            const sorted = [...entries].sort(sortFilesAndFolders)
            const collectedRows: ExplorerRow[] = []
            for (const entry of sorted) {
                collectedRows.push({ entry, depth })
                if (entry.type === 'folder' && explorerExpandedFolders[entry.path]) {
                    const children = folders[entry.path] || []
                    collectedRows.push(...buildRowsRecursive(children, depth + 1))
                }
            }
            return collectedRows
        }

        return buildRowsRecursive(currentEntries, 0)
    }, [currentEntries, explorerExpandedFolders, folders])
    const trimmedSearch = search.trim()
    const isSearchActive = trimmedSearch !== '' && hasActiveFolder
    const searchMatchesCurrentFolder =
        explorerSearchResults.folderPath === explorerFolderPath && explorerSearchResults.searchTerm !== ''
    const shouldUseSearchRows = isSearchActive && searchMatchesCurrentFolder
    const searchRows = useMemo(() => {
        if (!shouldUseSearchRows) {
            return []
        }

        return [...(explorerSearchResults.results || [])]
            .sort(sortFilesAndFolders)
            .map((entry) => ({ entry, depth: 0, isSearchResult: true }))
    }, [explorerSearchResults.results, shouldUseSearchRows])
    const isLoadingCurrentFolder = hasActiveFolder ? folderStates[explorerFolderPath] === 'loading' : false

    const breadcrumbSegments = splitPath(explorerFolderPath)
    const parentBreadcrumbSegments = breadcrumbSegments.slice(0, -1)
    const parentFolderPath = joinPath(parentBreadcrumbSegments)
    const parentRow: ExplorerRow | null = useMemo(() => {
        if (!hasActiveFolder) {
            return null
        }

        const isAtProjectRoot = breadcrumbSegments.length === 0
        return {
            entry: {
                id: `__parent-${explorerFolderPath || 'root'}`,
                path: isAtProjectRoot ? explorerFolderPath : parentFolderPath,
                type: 'folder',
            },
            depth: 0,
            isParentNavigation: true,
            navigatesToSearch: isAtProjectRoot,
        }
    }, [breadcrumbSegments.length, explorerFolderPath, hasActiveFolder, parentFolderPath])
    const contentRows = shouldUseSearchRows ? searchRows : rows
    const allEntries = useMemo(() => {
        const uniqueEntries = new Map<string, FileSystemEntry>()
        for (const { entry } of contentRows) {
            if (entry.path) {
                uniqueEntries.set(entry.path, entry)
            }
        }
        return Array.from(uniqueEntries.values())
    }, [contentRows])
    const displayRows = useMemo(
        () => (parentRow && !shouldUseSearchRows ? [parentRow, ...contentRows] : contentRows),
        [parentRow, contentRows, shouldUseSearchRows]
    )
    const draggableItemsById = useMemo(() => {
        const map = new Map<string, TreeDataItem>()
        for (const { entry, isParentNavigation } of displayRows) {
            if (isParentNavigation) {
                continue
            }
            const treeItem = convertEntryToTreeDataItem(entry as EntryWithProtocol)
            map.set(treeItem.id, treeItem)
        }
        return map
    }, [displayRows])
    const isLoadingRows = isSearchActive ? explorerSearchResultsLoading : isLoadingCurrentFolder
    const checkedItemCount = useMemo(() => Object.keys(checkedItems).length, [checkedItems])
    const handleToggleFolder = (path: string): void => {
        toggleExplorerFolderExpansion(path)
        if (!explorerExpandedFolders[path]) {
            loadFolder(path)
        }
    }

    const handleEntryActivate = (
        entry: FileSystemEntry,
        isParentNavigationRow?: boolean,
        navigatesToSearch?: boolean
    ): void => {
        if (isParentNavigationRow && navigatesToSearch) {
            setHighlightedExplorerEntryPath(null)
            setActiveExplorerFolderPath(null)
            return
        }
        if (entry.type === 'folder') {
            if (isParentNavigationRow && activeExplorerFolderPath) {
                setHighlightedExplorerEntryPath(activeExplorerFolderPath)
            } else {
                setHighlightedExplorerEntryPath(null)
            }
            setActiveExplorerFolderPath(entry.path)
        } else if (entry.href) {
            setHighlightedExplorerEntryPath(null)
            router.actions.push(entry.href)
        }
    }

    const renderCreatedBy = (entry: FileSystemEntry): JSX.Element => {
        const createdById = entry.meta?.created_by
        const createdBy = createdById ? users[createdById] : undefined
        if (!createdBy) {
            return <span className="text-sm text-muted">—</span>
        }
        return (
            <span className="flex items-center gap-2 min-w-0">
                <ProfilePicture user={createdBy} size="sm" className="shrink-0" />
                <span className="text-sm truncate text-primary">
                    {createdBy.first_name || createdBy.email || 'Unknown'}
                </span>
            </span>
        )
    }

    const renderCreatedAt = (entry: FileSystemEntry): string =>
        entry.created_at ? dayjs(entry.created_at).format('MMM D, YYYY') : '—'

    const highlightedFocusKey = useMemo(() => {
        if (!highlightedExplorerEntryPath) {
            return null
        }

        const targetIndex = displayRows.findIndex(({ entry }) => entry.path === highlightedExplorerEntryPath)

        if (targetIndex === -1) {
            return null
        }

        const entry = displayRows[targetIndex]?.entry
        if (!entry) {
            return null
        }

        const focusBase = String(entry.id ?? entry.path ?? targetIndex)
        return `${focusBase}-row`
    }, [displayRows, highlightedExplorerEntryPath])

    useEffect(() => {
        if (!listboxRef.current || !highlightedFocusKey) {
            return
        }
        listboxRef.current.focusItemByKey(highlightedFocusKey)
        setHighlightedExplorerEntryPath(null)
    }, [highlightedFocusKey, listboxRef, setHighlightedExplorerEntryPath])

    const getEntryFolderLabel = (entry: FileSystemEntry): string => {
        const segments = splitPath(entry.path)
        if (segments.length <= 1) {
            return 'Project root'
        }
        return joinPath(segments.slice(0, -1))
    }

    const highlightSearchText = (text: string): JSX.Element | string => {
        if (!shouldUseSearchRows || !trimmedSearch) {
            return text
        }
        return <SearchHighlightMultiple string={text} substring={trimmedSearch} />
    }

    const handleDragStart = useCallback(
        (dragEvent: DragStartEvent): void => {
            const activeId = String(dragEvent.active.id)
            const draggedItem = draggableItemsById.get(activeId)
            setActiveDragItem(draggedItem ?? null)
        },
        [draggableItemsById]
    )

    const handleDragEnd = useCallback(
        (dragEvent: DragEndEvent): void => {
            const itemToId = (item: FileSystemEntry): string =>
                item.type === 'folder' ? `project://${item.path}` : `project/${item.id}`

            const oldId = String(dragEvent.active.id)
            const newId = dragEvent.over?.id ? String(dragEvent.over.id) : null

            if (!newId || oldId === newId) {
                dragEvent.activatorEvent?.stopPropagation?.()
                dragEvent.activatorEvent?.preventDefault?.()
                setActiveDragItem(null)
                return
            }

            const oldItem = allEntries.find((item) => itemToId(item) === oldId)
            const newItem = allEntries.find((item) => itemToId(item) === newId)

            if (!oldItem) {
                setActiveDragItem(null)
                return
            }

            const folder = newItem
                ? newItem.path || ''
                : newId && String(newId).startsWith('project://')
                  ? String(newId).substring('project://'.length)
                  : ''

            if (checkedItems[oldId]) {
                moveCheckedItems(folder)
            } else {
                const { newPath, isValidMove } = calculateMovePath(oldItem, folder)
                if (isValidMove) {
                    moveItem(oldItem, newPath, false, projectTreeLogicProps.key)
                }
            }

            setActiveDragItem(null)
        },
        [allEntries, checkedItems, moveCheckedItems, moveItem, projectTreeLogicProps.key]
    )

    if (!hasActiveFolder) {
        return null
    }

    const rowGridClass = shouldUseSearchRows
        ? 'grid grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)_200px_160px_48px]'
        : 'grid grid-cols-[minmax(0,1fr)_200px_160px_48px]'

    return (
        <DndContext
            sensors={sensors}
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
            onDragCancel={() => setActiveDragItem(null)}
        >
            <div className="flex flex-col gap-3 p-3">
                <div className="rounded bg-bg-300">
                    <div
                        className={clsx(rowGridClass, 'border-b border-border px-3 py-2 text-xs uppercase text-muted')}
                    >
                        <div className="flex items-center gap-2 pr-3 pl-6">
                            <span>Name</span>
                            {isLoadingRows && <Spinner size="small" />}
                        </div>
                        {shouldUseSearchRows && <div className="px-3 pl-3">Folder</div>}
                        <div className="px-3 pl-6">Created by</div>
                        <div className="px-3 pl-6">Created at</div>
                        <div className="flex items-center justify-end px-2">
                            <span aria-hidden="true" className="inline-block size-5" />
                            <span className="sr-only">Actions</span>
                        </div>
                    </div>
                    <ListBox.Group groupId="project-explorer">
                        {displayRows.map(
                            ({ entry, depth, isParentNavigation, navigatesToSearch, isSearchResult }, rowIndex) => {
                                const isParentNavigationRow = !!isParentNavigation
                                const isExitNavigationRow = !!navigatesToSearch
                                const isFolder = entry.type === 'folder'
                                const isExpandableFolder = isFolder && !isParentNavigationRow && !isSearchResult
                                const isExpanded = isExpandableFolder && !!explorerExpandedFolders[entry.path]
                                const iconType: FileSystemIconType = isParentNavigationRow
                                    ? 'folder_open'
                                    : isExpandableFolder && isExpanded
                                      ? 'folder_open'
                                      : (entry.type as FileSystemIconType) || 'default_icon_type'
                                const icon = iconForType(iconType)
                                const focusBase = String(entry.id ?? entry.path ?? rowIndex)
                                const rawNameLabel = isParentNavigationRow
                                    ? '..'
                                    : splitPath(entry.path).pop() || entry.path
                                const nameLabel = highlightSearchText(rawNameLabel)
                                const folderLabel = highlightSearchText(getEntryFolderLabel(entry))
                                const isHighlighted = highlightedExplorerEntryPath === entry.path
                                const handleRowClick = (event: MouseEvent<HTMLElement>): void => {
                                    const isClickOnActiveArea = (event.target as HTMLElement | null)?.closest(
                                        '[data-explorer-row-clickable]'
                                    )

                                    if (!isClickOnActiveArea) {
                                        event.preventDefault()
                                        return
                                    }

                                    event.preventDefault()
                                    handleEntryActivate(entry, isParentNavigationRow, isExitNavigationRow)
                                }

                                const handleRowDoubleClick = (event: MouseEvent<HTMLElement>): void => {
                                    event.preventDefault()
                                    handleEntryActivate(entry, isParentNavigationRow, isExitNavigationRow)
                                }
                                const handleRowFocus = (): void => {
                                    if (highlightedExplorerEntryPath && highlightedExplorerEntryPath !== entry.path) {
                                        setHighlightedExplorerEntryPath(null)
                                    }
                                }
                                const rowIndent = depth > 0 ? depth * CHILD_INDENT_PX : 0
                                const nameColumnIndentStyle: CSSProperties | undefined = rowIndent
                                    ? { marginLeft: rowIndent }
                                    : undefined
                                const treeItem = isParentNavigationRow ? null : convertEntryToTreeDataItem(entry)
                                const rowKey = `${entry.id ?? entry.path}-${rowIndex}`
                                const listBoxItem = (
                                    <ExplorerRowListItem
                                        key={rowKey}
                                        rowIndex={rowIndex}
                                        rowKey={rowKey}
                                        focusBase={focusBase}
                                        rowGridClass={rowGridClass}
                                        isHighlighted={isHighlighted}
                                        handleRowClick={handleRowClick}
                                        handleRowDoubleClick={handleRowDoubleClick}
                                        handleRowFocus={handleRowFocus}
                                        nameColumnIndentStyle={nameColumnIndentStyle}
                                        isExpandableFolder={isExpandableFolder}
                                        isExpanded={isExpanded}
                                        handleToggleFolder={handleToggleFolder}
                                        icon={icon}
                                        nameLabel={nameLabel}
                                        folderStates={folderStates}
                                        entry={entry}
                                        shouldUseSearchRows={shouldUseSearchRows}
                                        folderLabel={folderLabel}
                                        renderCreatedBy={renderCreatedBy}
                                        renderCreatedAt={renderCreatedAt}
                                        isParentNavigationRow={isParentNavigationRow}
                                        treeItem={treeItem}
                                        projectTreeLogicProps={projectTreeLogicProps}
                                    />
                                )

                                if (isParentNavigationRow || !treeItem) {
                                    return listBoxItem
                                }

                                return (
                                    <ContextMenu key={rowKey}>
                                        <ContextMenuTrigger asChild>{listBoxItem}</ContextMenuTrigger>
                                        <ContextMenuContent loop className="max-w-[250px]">
                                            <ContextMenuGroup className="group/colorful-product-icons colorful-product-icons-true">
                                                <MenuItems
                                                    item={treeItem}
                                                    type="context"
                                                    root={projectTreeLogicProps.root}
                                                    logicKey={projectTreeLogicProps.key}
                                                    onlyTree={false}
                                                    showSelectMenuOption={false}
                                                />
                                            </ContextMenuGroup>
                                        </ContextMenuContent>
                                    </ContextMenu>
                                )
                            }
                        )}
                        {isLoadingRows && contentRows.length === 0 ? (
                            <div className="flex items-center gap-2 px-3 py-1.5 ml-6 text-muted border-t border-border">
                                <Spinner /> {isSearchActive ? 'Searching within folder…' : 'Loading folder...'}
                            </div>
                        ) : null}
                        {!isLoadingRows && contentRows.length === 0 ? (
                            <div className="px-3 py-1.5 ml-12 text-sm text-muted border-t border-border">
                                {isSearchActive
                                    ? 'No matching files or folders in this location.'
                                    : 'No files in this folder.'}
                            </div>
                        ) : null}
                    </ListBox.Group>
                    <div
                        ref={setRootDropZoneRef}
                        className={clsx(
                            'mt-2 flex h-12 items-center justify-center rounded border border-dashed text-sm transition-colors',
                            isDragging ? 'border-border text-muted' : 'border-transparent text-transparent',
                            isOverRoot && 'border-accent bg-accent-highlight-secondary text-primary'
                        )}
                    >
                        Drop here to move into this folder
                    </div>
                </div>
            </div>

            <DragOverlay dropAnimation={null}>
                {activeDragItem ? (
                    <ButtonPrimitive className="flex items-center gap-2 rounded border border-border bg-surface px-3 py-2 shadow-lg">
                        <span className="shrink-0 text-primary">
                            {iconForType((activeDragItem.record?.type as FileSystemIconType) || 'default_icon_type')}
                        </span>
                        <span className="truncate font-medium text-primary">
                            {activeDragItem.displayName || activeDragItem.name}
                        </span>
                        {checkedItems[activeDragItem.id] && checkedItemCount > 1 ? (
                            <span className="ml-1 text-xs rounded-full bg-primary-highlight px-2 py-0.5 whitespace-nowrap">
                                +{checkedItemCount - 1} other{checkedItemCount - 1 === 1 ? '' : 's'}
                            </span>
                        ) : null}
                    </ButtonPrimitive>
                ) : null}
            </DragOverlay>
        </DndContext>
    )
}

interface ExplorerRowListItemProps extends HTMLAttributes<HTMLLIElement> {
    rowIndex: number
    rowKey: string
    focusBase: string
    rowGridClass: string
    isHighlighted: boolean
    handleRowClick: (event: MouseEvent<HTMLElement>) => void
    handleRowDoubleClick: (event: MouseEvent<HTMLElement>) => void
    handleRowFocus: () => void
    nameColumnIndentStyle?: CSSProperties
    isExpandableFolder: boolean
    isExpanded: boolean
    handleToggleFolder: (path: string) => void
    icon: JSX.Element
    nameLabel: JSX.Element | string
    folderStates: Record<string, string | undefined>
    entry: FileSystemEntry
    shouldUseSearchRows: boolean
    folderLabel: JSX.Element | string
    renderCreatedBy: (entry: FileSystemEntry) => JSX.Element
    renderCreatedAt: (entry: FileSystemEntry) => string
    isParentNavigationRow: boolean
    treeItem: TreeDataItem | null
    projectTreeLogicProps: ProjectTreeLogicProps
}

function ExplorerRowListItem({
    rowIndex,
    rowKey,
    focusBase,
    rowGridClass,
    isHighlighted,
    handleRowClick,
    handleRowDoubleClick,
    handleRowFocus,
    nameColumnIndentStyle,
    isExpandableFolder,
    isExpanded,
    handleToggleFolder,
    icon,
    nameLabel,
    folderStates,
    entry,
    shouldUseSearchRows,
    folderLabel,
    renderCreatedBy,
    renderCreatedAt,
    isParentNavigationRow,
    treeItem,
    projectTreeLogicProps,
    ...contextMenuProps
}: ExplorerRowListItemProps): JSX.Element {
    const droppableId = isParentNavigationRow ? `project://${entry.path}` : (treeItem?.id ?? rowKey)
    const isDraggable = !!treeItem?.record?.path
    const isDroppable =
        isParentNavigationRow ||
        (!!treeItem?.record?.path && isExpandableFolder && !isParentNavigationRow && !treeItem?.record?.href)

    const {
        attributes,
        listeners,
        setNodeRef: setDraggableNodeRef,
    } = useDraggable({
        id: droppableId,
        disabled: !isDraggable,
    })
    const { setNodeRef: setDroppableNodeRef, isOver } = useDroppable({
        id: droppableId,
        disabled: !isDroppable,
    })

    const setNodeRefs = useCallback(
        (node: HTMLElement | null) => {
            setDraggableNodeRef(node)
            setDroppableNodeRef(node)
        },
        [setDraggableNodeRef, setDroppableNodeRef]
    )

    const dragProps = isDraggable ? { ...attributes, ...listeners } : {}
    const droppableHighlight = isDroppable && isOver

    return (
        <ListBox.Item
            asChild
            row={rowIndex}
            column={0}
            focusKey={`${focusBase}-row`}
            index={rowIndex}
            key={rowKey}
            ref={setNodeRefs}
            {...dragProps}
            {...contextMenuProps}
        >
            <Link
                to={entry.href || '#'}
                data-explorer-entry-path={entry.path}
                data-explorer-entry-type={entry.type}
                data-explorer-entry-parent={isParentNavigationRow ? 'true' : 'false'}
                data-explorer-entry-expandable={isExpandableFolder ? 'true' : 'false'}
                className={clsx(
                    rowGridClass,
                    'group/explorer-row rounded border-t border-border text-primary no-underline focus-visible:outline-none first:border-t-0 data-[focused=true]:bg-primary-alt-highlight data-[focused=true]:text-primary cursor-default',
                    isHighlighted && 'bg-primary-alt-highlight text-primary',
                    droppableHighlight && 'ring-2 ring-inset ring-accent bg-accent-highlight-secondary',
                    isParentNavigationRow && 'py-0.5'
                )}
                onClick={handleRowClick}
                onDoubleClick={handleRowDoubleClick}
                onFocus={handleRowFocus}
            >
                <div className="flex items-center gap-2 px-3 py-1.5 min-w-0 text-sm" style={nameColumnIndentStyle}>
                    <span className="flex w-5 justify-center">
                        {isExpandableFolder ? (
                            <ButtonPrimitive
                                size="xs"
                                iconOnly
                                tabIndex={-1}
                                className="shrink-0"
                                onMouseDown={(event) => event.preventDefault()}
                                onClick={(event) => {
                                    event.stopPropagation()
                                    event.preventDefault()
                                    handleToggleFolder(entry.path)
                                }}
                                aria-label={isExpanded ? 'Collapse folder' : 'Expand folder'}
                            >
                                <IconChevronRight
                                    className={`size-3 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                                />
                            </ButtonPrimitive>
                        ) : (
                            <span className="block w-3" />
                        )}
                    </span>
                    <span data-explorer-row-clickable className="flex min-w-0 items-center gap-2 cursor-pointer">
                        <span className="shrink-0 text-primary">{icon}</span>
                        <span className="truncate">{nameLabel}</span>
                    </span>
                    {isExpandableFolder && folderStates[entry.path] === 'loading' ? (
                        <Spinner className="size-3" />
                    ) : null}
                </div>
                {shouldUseSearchRows && (
                    <div className="flex items-center gap-2 px-3 py-1.5 min-w-0 text-sm text-primary">
                        <span className="truncate">{folderLabel}</span>
                    </div>
                )}
                <div className="flex items-center gap-2 px-3 py-1.5 min-w-0 text-sm text-primary">
                    {renderCreatedBy(entry)}
                </div>
                <div className="flex items-center gap-2 px-3 py-1.5 min-w-0 text-sm text-muted">
                    {renderCreatedAt(entry)}
                </div>
                <div className="flex items-center justify-end px-2 py-1.5">
                    {!isParentNavigationRow && treeItem ? (
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <ButtonPrimitive
                                    size="xxs"
                                    iconOnly
                                    onClick={(event) => {
                                        event.preventDefault()
                                        event.stopPropagation()
                                    }}
                                    className="opacity-0 transition-opacity group-hover/explorer-row:opacity-100 group-focus-visible/explorer-row:opacity-100"
                                    aria-label="Open file actions"
                                >
                                    <IconEllipsis className="size-3" />
                                </ButtonPrimitive>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="max-w-[250px]">
                                <DropdownMenuGroup className="group/colorful-product-icons colorful-product-icons-true">
                                    <MenuItems
                                        item={treeItem}
                                        type="dropdown"
                                        root={projectTreeLogicProps.root}
                                        logicKey={projectTreeLogicProps.key}
                                        onlyTree={false}
                                        showSelectMenuOption={false}
                                    />
                                </DropdownMenuGroup>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    ) : (
                        <span aria-hidden="true" className="inline-block size-5" />
                    )}
                </div>
            </Link>
        </ListBox.Item>
    )
}
