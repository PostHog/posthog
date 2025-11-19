import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { MouseEvent, useEffect, useMemo } from 'react'

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
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { joinPath, sortFilesAndFolders, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { TreeDataItem } from '~/lib/lemon-ui/LemonTree/LemonTree'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { getNewTabProjectTreeLogicProps, newTabSceneLogic } from '../newTabSceneLogic'

const CHILD_INDENT_PX = 24

const convertEntryToTreeDataItem = (entry: FileSystemEntry): TreeDataItem => ({
    id: String(entry.id || entry.path || 'entry'),
    name: splitPath(entry.path).pop() || entry.path || 'Unnamed entry',
    record: {
        ...entry,
    },
})

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
    const { folders, folderStates, users } = useValues(projectTreeLogic(projectTreeLogicProps))
    const { loadFolder } = useActions(projectTreeLogic(projectTreeLogicProps))
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

    useEffect(() => {
        if (activeExplorerFolderPath === null) {
            return
        }
        if (!folders[activeExplorerFolderPath] && folderStates[activeExplorerFolderPath] !== 'loading') {
            loadFolder(activeExplorerFolderPath)
        }
    }, [activeExplorerFolderPath, folders, folderStates, loadFolder])

    const hasActiveFolder = activeExplorerFolderPath !== null
    const explorerFolderPath = activeExplorerFolderPath ?? ''
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
    const displayRows = useMemo(
        () => (parentRow && !shouldUseSearchRows ? [parentRow, ...contentRows] : contentRows),
        [parentRow, contentRows, shouldUseSearchRows]
    )
    const isLoadingRows = isSearchActive ? explorerSearchResultsLoading : isLoadingCurrentFolder
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
    }, [highlightedFocusKey, listboxRef])

    if (!hasActiveFolder) {
        return null
    }

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

    const rowGridClass = shouldUseSearchRows
        ? 'grid grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)_200px_160px]'
        : 'grid grid-cols-[minmax(0,1fr)_200px_160px]'

    return (
        <div className="flex flex-col gap-3 p-3">
            <div className="rounded bg-bg-300">
                {isSearchActive && (
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2 text-xs text-muted">
                        <span className="truncate">
                            Searching {folderDisplayName} for “{trimmedSearch}”
                        </span>
                        {explorerSearchResultsLoading && <Spinner size="small" />}
                    </div>
                )}
                <div
                    className={clsx(
                        'grid grid-cols-[minmax(0,1fr)_200px_160px_auto] border-b border-border px-3 py-2 text-xs uppercase text-muted',
                        rowGridClass
                    )}
                >
                    <div className="pr-3 pl-6">Name</div>
                    {shouldUseSearchRows && <div className="px-3 pl-3">Folder</div>}
                    <div className="px-3 pl-6">Created by</div>
                    <div className="px-3 pl-6">Created at</div>
                    <div className="px-3 text-right">
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
                            const icon = iconForType(
                                isParentNavigationRow
                                    ? 'folder_open'
                                    : (entry.type as FileSystemIconType) || 'default_icon_type'
                            )
                            const focusBase = String(entry.id ?? entry.path ?? rowIndex)
                            const rawNameLabel = isParentNavigationRow
                                ? '..'
                                : splitPath(entry.path).pop() || entry.path
                            const nameLabel = highlightSearchText(rawNameLabel)
                            const folderLabel = highlightSearchText(getEntryFolderLabel(entry))
                            const isHighlighted = highlightedExplorerEntryPath === entry.path
                            const handleRowClick = (event: MouseEvent<HTMLElement>): void => {
                                event.preventDefault()
                                handleEntryActivate(entry, isParentNavigationRow, isExitNavigationRow)
                            }
                            const handleRowFocus = (): void => {
                                if (highlightedExplorerEntryPath && highlightedExplorerEntryPath !== entry.path) {
                                    setHighlightedExplorerEntryPath(null)
                                }
                            }
                            const rowIndent = depth > 0 ? depth * CHILD_INDENT_PX : 0
                            const treeItem = isParentNavigationRow ? null : convertEntryToTreeDataItem(entry)
                            const rowKey = `${entry.id ?? entry.path}-${rowIndex}`
                            const listBoxItem = (
                                <ListBox.Item
                                    asChild
                                    row={rowIndex}
                                    column={0}
                                    focusKey={`${focusBase}-row`}
                                    index={rowIndex}
                                    key={rowKey}
                                >
                                    <Link
                                        to={entry.href || '#'}
                                        className={clsx(
                                            rowGridClass,
                                            'group/explorer-row grid grid-cols-[minmax(0,1fr)_200px_160px_auto] border-t border-border text-primary no-underline focus-visible:outline-none first:border-t-0 data-[focused=true]:bg-primary-alt-highlight data-[focused=true]:text-primary',
                                            isHighlighted && 'bg-primary-alt-highlight text-primary'
                                        )}
                                        style={rowIndent ? { paddingLeft: rowIndent } : undefined}
                                        onClick={handleRowClick}
                                        onFocus={handleRowFocus}
                                    >
                                        <div className="flex items-center gap-2 px-3 py-2 min-w-0 text-sm">
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
                                            <span className="shrink-0 text-primary">{icon}</span>
                                            <span className="truncate">{nameLabel}</span>
                                            {isExpandableFolder && folderStates[entry.path] === 'loading' ? (
                                                <Spinner className="size-3" />
                                            ) : null}
                                        </div>
                                        {shouldUseSearchRows && (
                                            <div className="flex items-center gap-2 px-3 py-2 min-w-0 text-sm text-primary">
                                                <span className="truncate">{folderLabel}</span>
                                            </div>
                                        )}
                                        <div className="flex items-center gap-2 px-3 py-2 min-w-0 text-sm text-primary">
                                            {renderCreatedBy(entry)}
                                        </div>
                                        <div className="flex items-center gap-2 px-3 py-2 min-w-0 text-sm text-muted">
                                            {renderCreatedAt(entry)}
                                        </div>
                                        <div className="flex items-center justify-end px-2 py-2">
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
                                            ) : null}
                                        </div>
                                    </Link>
                                </ListBox.Item>
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
                        <div className="flex items-center gap-2 px-3 py-2 ml-6 text-muted border-t border-border">
                            <Spinner /> {isSearchActive ? 'Searching within folder…' : 'Loading folder...'}
                        </div>
                    ) : null}
                    {!isLoadingRows && contentRows.length === 0 ? (
                        <div className="px-3 py-2 ml-12 text-sm text-muted border-t border-border">
                            {isSearchActive
                                ? 'No matching files or folders in this location.'
                                : 'No files in this folder.'}
                        </div>
                    ) : null}
                </ListBox.Group>
            </div>
        </div>
    )
}
