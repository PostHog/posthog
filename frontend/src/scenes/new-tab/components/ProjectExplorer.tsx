import { useDraggable, useDroppable } from '@dnd-kit/core'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import {
    CSSProperties,
    HTMLAttributes,
    KeyboardEvent,
    MouseEvent,
    useCallback,
    useEffect,
    useRef,
    useState,
} from 'react'

import { IconChevronRight, IconEllipsis } from '@posthog/icons'
import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenu, ContextMenuContent, ContextMenuGroup, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'

import {
    ProjectDragData,
    projectDragDataFromEntry,
    projectDroppableId,
    useProjectDragState,
} from '~/layout/panel-layout/ProjectTree/ProjectDragAndDropContext'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { MenuItems } from '~/layout/panel-layout/ProjectTree/menus/MenuItems'
import { ProjectTreeLogicProps } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { getItemId, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { TreeDataItem } from '~/lib/lemon-ui/LemonTree/LemonTree'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { projectExplorerLogic } from './projectExplorerLogic'

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

export function ProjectExplorer({
    tabId,
    listboxRef,
}: {
    tabId: string
    listboxRef: React.RefObject<ListBoxHandle>
}): JSX.Element | null {
    const logic = projectExplorerLogic({ tabId })
    const {
        projectTreeLogicProps,
        checkedItems,
        folderStates,
        editingItemId,
        activeExplorerFolderPath,
        explorerExpandedFolders,
        highlightedExplorerEntryPath,
        droppableScope,
        rootDroppableId,
        hasActiveFolder,
        explorerFolderPath,
        displayRows,
        contentRows,
        shouldUseSearchRows,
        isLoadingRows,
        rowGridClass,
        isSearchActive,
        highlightedFocusKey,
        getEntryFolderLabel,
        highlightSearchText,
        getParentRowFocusKey,
        renderCreatedBy,
        renderCreatedAt,
    } = useValues(logic)
    const {
        loadFolder,
        rename,
        setEditingItemId,
        setActiveExplorerFolderPath,
        toggleExplorerFolderExpansion,
        setHighlightedExplorerEntryPath,
    } = useActions(logic)
    const { activeItem } = useProjectDragState()
    const { setNodeRef: setRootDropZoneRef, isOver: isOverRoot } = useDroppable({ id: rootDroppableId })
    const isDragging = !!activeItem
    const [pendingFocusKey, setPendingFocusKey] = useState<string | null>(null)
    const preserveCurrentFocus = useCallback(() => {
        const focusHistory = listboxRef.current?.getFocusHistory()
        const lastFocusKey = focusHistory?.[focusHistory.length - 1]

        if (lastFocusKey) {
            setPendingFocusKey(lastFocusKey)
        }
    }, [listboxRef])

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
                setHighlightedExplorerEntryPath(explorerFolderPath)
            }
            setActiveExplorerFolderPath(entry.path)
        } else if (entry.href) {
            setHighlightedExplorerEntryPath(null)
            router.actions.push(entry.href)
        }
    }

    useEffect(() => {
        if (!listboxRef.current || !highlightedFocusKey) {
            return
        }
        if (listboxRef.current.focusItemByKey(highlightedFocusKey)) {
            setHighlightedExplorerEntryPath(null)
        }
    }, [highlightedFocusKey, listboxRef, setHighlightedExplorerEntryPath])

    useEffect(() => {
        if (!pendingFocusKey) {
            return
        }

        if (listboxRef.current?.focusItemByKey(pendingFocusKey)) {
            setPendingFocusKey(null)
        }
    }, [displayRows, listboxRef, pendingFocusKey])

    if (!hasActiveFolder) {
        return null
    }

    return (
        <div className="flex flex-col gap-3">
            <LemonBanner type="info">
                This is a flagged feature <code>new-tab-project-explorer</code>. Share your feedback with
                #team-platform-ux.
            </LemonBanner>
            <div className="rounded bg-bg-300">
                <div className={clsx(rowGridClass, 'border-b border-border px-3 py-2 text-xs uppercase text-muted')}>
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
                            const focusKey = `${focusBase}-row`
                            const rawNameLabel = isParentNavigationRow
                                ? '..'
                                : splitPath(entry.path).pop() || entry.path
                            const nameLabel = highlightSearchText(rawNameLabel)
                            const folderLabel = highlightSearchText(getEntryFolderLabel(entry))
                            const isHighlighted = highlightedExplorerEntryPath === entry.path

                            const handleRowKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
                                if (event.key === 'Enter') {
                                    event.preventDefault()
                                    handleEntryActivate(entry, isParentNavigationRow, isExitNavigationRow)
                                }
                            }

                            const handleRowDoubleClick = (event: MouseEvent<HTMLElement>): void => {
                                if (isEditing) {
                                    event.preventDefault()
                                    return
                                }

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
                            const isEditing = editingItemId === treeItem?.id
                            const handleRowClick = (event: MouseEvent<HTMLElement>): void => {
                                if (isEditing) {
                                    event.preventDefault()
                                    return
                                }

                                const isKeyboardInitiated = event.detail === 0
                                const isClickOnActiveArea = (event.target as HTMLElement | null)?.closest(
                                    '[data-explorer-row-clickable]'
                                )

                                if (!isKeyboardInitiated && !isClickOnActiveArea) {
                                    event.preventDefault()
                                    return
                                }

                                event.preventDefault()
                                listboxRef.current?.focusItemByKey(focusKey)
                                if (isFolder && !isExitNavigationRow && !isParentNavigationRow) {
                                    setPendingFocusKey(getParentRowFocusKey(entry.path || ''))
                                }
                                handleEntryActivate(entry, isParentNavigationRow, isExitNavigationRow)
                            }
                            const rowKey = `${entry.id ?? entry.path}-${rowIndex}`
                            const listBoxItem = (
                                <ExplorerRowListItem
                                    key={rowKey}
                                    rowIndex={rowIndex}
                                    rowKey={rowKey}
                                    focusBase={focusBase}
                                    focusKey={focusKey}
                                    rowGridClass={rowGridClass}
                                    isHighlighted={isHighlighted}
                                    handleRowClick={handleRowClick}
                                    handleRowDoubleClick={handleRowDoubleClick}
                                    handleRowKeyDown={handleRowKeyDown}
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
                                    isEditing={isEditing}
                                    rawNameLabel={rawNameLabel}
                                    rename={rename}
                                    setEditingItemId={setEditingItemId}
                                    preserveCurrentFocus={preserveCurrentFocus}
                                    checkedItems={checkedItems}
                                    droppableScope={droppableScope}
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
    )
}

interface ExplorerRowListItemProps extends HTMLAttributes<HTMLLIElement> {
    rowIndex: number
    rowKey: string
    focusBase: string
    focusKey: string
    rowGridClass: string
    isHighlighted: boolean
    handleRowClick: (event: MouseEvent<HTMLElement>) => void
    handleRowDoubleClick: (event: MouseEvent<HTMLElement>) => void
    handleRowKeyDown: (event: KeyboardEvent<HTMLElement>) => void
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
    isEditing: boolean
    rawNameLabel: string
    rename: (value: string, item: FileSystemEntry) => void
    setEditingItemId: (id: string) => void
    preserveCurrentFocus: () => void
    checkedItems: Record<string, boolean>
    droppableScope: string
}

function ExplorerRowListItem({
    rowIndex,
    rowKey,
    focusBase,
    focusKey,
    rowGridClass,
    isHighlighted,
    handleRowClick,
    handleRowDoubleClick,
    handleRowKeyDown,
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
    isEditing,
    rawNameLabel,
    rename,
    setEditingItemId,
    preserveCurrentFocus,
    checkedItems,
    droppableScope,
    ...contextMenuProps
}: ExplorerRowListItemProps): JSX.Element {
    const protocol = (entry as EntryWithProtocol).protocol ?? 'project://'
    const baseTreeItemId = treeItem?.id ?? rowKey
    const droppableId = isParentNavigationRow
        ? projectDroppableId(entry.path || '', protocol, droppableScope)
        : projectDroppableId(treeItem?.record?.path || baseTreeItemId, protocol, droppableScope)
    const isDraggable = !!treeItem?.record?.path
    const isDroppable =
        isParentNavigationRow ||
        (!!treeItem?.record?.path && isExpandableFolder && !isParentNavigationRow && !treeItem?.record?.href)
    const dragData: ProjectDragData | undefined =
        isDraggable && treeItem?.record
            ? projectDragDataFromEntry(
                  treeItem.record as FileSystemEntry,
                  projectTreeLogicProps.key,
                  checkedItems[baseTreeItemId]
                      ? Object.keys(checkedItems).filter((checkedId) => checkedItems[checkedId])
                      : undefined
              )
            : undefined

    const {
        attributes,
        listeners,
        setNodeRef: setDraggableNodeRef,
    } = useDraggable({
        id: droppableId,
        data: dragData,
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
    const handleRenameSubmit = useCallback(
        (nextName: string): void => {
            const trimmedName = nextName.trim()
            if (!trimmedName || trimmedName === rawNameLabel) {
                setEditingItemId('')
                return
            }

            rename(trimmedName, entry)
        },
        [entry, rawNameLabel, rename, setEditingItemId]
    )
    const handleRenameCancel = useCallback((): void => {
        setEditingItemId('')
    }, [setEditingItemId])

    return (
        <ListBox.Item
            asChild
            row={rowIndex}
            column={0}
            focusKey={focusKey}
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
                onKeyDown={handleRowKeyDown}
                onFocus={handleRowFocus}
            >
                <div className="flex items-center gap-2 px-3 py-1.5 min-w-0 text-sm" style={nameColumnIndentStyle}>
                    <span className="flex w-5 justify-center">
                        {isExpandableFolder ? (
                            <ButtonPrimitive
                                size="xxs"
                                iconOnly
                                tabIndex={-1}
                                className="shrink-0"
                                onMouseDown={(event) => {
                                    preserveCurrentFocus()
                                    event.stopPropagation()
                                    event.preventDefault()
                                    handleToggleFolder(entry.path)
                                }}
                                onClick={(event) => {
                                    event.preventDefault()
                                }}
                                onDoubleClick={(event) => {
                                    event.stopPropagation()
                                    event.preventDefault()
                                }}
                                aria-label={isExpanded ? 'Collapse folder' : 'Expand folder'}
                            >
                                <IconChevronRight
                                    className={`size-3 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                                />
                            </ButtonPrimitive>
                        ) : (
                            <ButtonPrimitive
                                size="xxs"
                                iconOnly
                                tabIndex={-1}
                                className="pointer-events-none opacity-0"
                                aria-hidden
                            >
                                {/* Hidden spacer */}
                                <IconChevronRight className="size-3" />
                            </ButtonPrimitive>
                        )}
                    </span>
                    <span
                        data-explorer-row-clickable={isEditing ? undefined : 'true'}
                        className={clsx('flex min-w-0 items-center gap-2 w-full', !isEditing && 'cursor-pointer')}
                    >
                        <span className="shrink-0 text-primary">{icon}</span>
                        {isEditing ? (
                            <ExplorerNameEditor
                                initialName={rawNameLabel}
                                onSubmit={handleRenameSubmit}
                                onCancel={handleRenameCancel}
                            />
                        ) : (
                            <span className="truncate">{nameLabel}</span>
                        )}
                    </span>
                    {isExpandableFolder && folderStates[entry.path] === 'loading' ? (
                        <Spinner className="size-3" />
                    ) : null}
                </div>
                {shouldUseSearchRows && (
                    <div className="flex items-center gap-2 px-3 py-1.5 min-w-0 text-sm text-primary w-full">
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

interface ExplorerNameEditorProps {
    initialName: string
    onSubmit: (value: string) => void
    onCancel: () => void
}

function ExplorerNameEditor({ initialName, onSubmit, onCancel }: ExplorerNameEditorProps): JSX.Element {
    const [name, setName] = useState(initialName)
    const inputRef = useRef<HTMLInputElement>(null)
    const hasFinishedRef = useRef(false)

    useEffect(() => {
        setName(initialName)
        hasFinishedRef.current = false
    }, [initialName])

    useEffect((): void => {
        window.setTimeout(() => {
            inputRef.current?.focus()
        }, 2)
    }, [])

    const finishEditing = useCallback(
        (shouldSave: boolean): void => {
            if (hasFinishedRef.current) {
                return
            }
            hasFinishedRef.current = true

            if (shouldSave) {
                onSubmit(name)
            } else {
                onCancel()
            }
        },
        [name, onCancel, onSubmit]
    )

    return (
        <input
            ref={inputRef}
            className="w-full rounded border border-border bg-surface-primary text-sm text-primary input-like"
            value={name}
            onChange={(event) => setName(event.target.value)}
            onBlur={() => finishEditing(true)}
            onKeyDown={(event) => {
                if (event.key === 'Enter') {
                    event.preventDefault()
                    event.stopPropagation()
                    finishEditing(true)
                } else if (event.key === 'Escape') {
                    event.preventDefault()
                    event.stopPropagation()
                    finishEditing(false)
                }
            }}
        />
    )
}
