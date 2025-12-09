import { connect, kea, key, path, props, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { projectDroppableId } from '~/layout/panel-layout/ProjectTree/ProjectDragAndDropContext'
import { ProjectTreeLogicProps, projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { joinPath, sortFilesAndFolders, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { getNewTabProjectTreeLogicProps, newTabSceneLogic } from '../newTabSceneLogic'
import type { projectExplorerLogicType } from './projectExplorerLogicType'

export interface ProjectExplorerLogicProps {
    tabId: string
}

export interface ExplorerRow {
    entry: FileSystemEntry
    depth: number
    isParentNavigation?: boolean
    navigatesToSearch?: boolean
    isSearchResult?: boolean
}

export interface JSXElement extends JSX.Element {}

export const projectExplorerLogic = kea<projectExplorerLogicType>([
    path(['scenes', 'new-tab', 'components', 'projectExplorerLogic']),
    props({} as ProjectExplorerLogicProps),
    key(({ tabId }) => tabId),
    connect(({ tabId }: ProjectExplorerLogicProps) => {
        const projectTreeLogicProps = getNewTabProjectTreeLogicProps(tabId)
        return {
            values: [
                projectTreeLogic(projectTreeLogicProps),
                ['checkedItems', 'folders', 'folderStates', 'users', 'editingItemId'],
                newTabSceneLogic({ tabId }),
                [
                    'activeExplorerFolderPath',
                    'explorerExpandedFolders',
                    'highlightedExplorerEntryPath',
                    'search',
                    'explorerSearchResults',
                    'explorerSearchResultsLoading',
                ],
            ],
            actions: [
                projectTreeLogic(projectTreeLogicProps),
                ['loadFolder', 'rename', 'setEditingItemId'],
                newTabSceneLogic({ tabId }),
                ['setActiveExplorerFolderPath', 'toggleExplorerFolderExpansion', 'setHighlightedExplorerEntryPath'],
            ],
        }
    }),
    selectors({
        projectTreeLogicProps: [
            (_, props) => [props.tabId],
            (tabId): ProjectTreeLogicProps => getNewTabProjectTreeLogicProps(tabId),
        ],
        droppableScope: [(_, props) => [props.tabId], (tabId): string => `project-explorer-${tabId}`],
        explorerFolderPath: [
            (s) => [s.activeExplorerFolderPath],
            (activeExplorerFolderPath): string => activeExplorerFolderPath ?? '',
        ],
        hasActiveFolder: [
            (s) => [s.activeExplorerFolderPath],
            (activeExplorerFolderPath): boolean => activeExplorerFolderPath !== null,
        ],
        rootDroppableId: [
            (s) => [s.explorerFolderPath, s.droppableScope],
            (explorerFolderPath, droppableScope): string =>
                projectDroppableId(explorerFolderPath, 'project://', `${droppableScope}-root`),
        ],
        currentEntries: [
            (s) => [s.hasActiveFolder, s.folders, s.explorerFolderPath],
            (hasActiveFolder, folders, explorerFolderPath): FileSystemEntry[] =>
                hasActiveFolder ? folders[explorerFolderPath] || [] : [],
        ],
        rows: [
            (s) => [s.currentEntries, s.explorerExpandedFolders, s.folders],
            (currentEntries, explorerExpandedFolders, folders): ExplorerRow[] => {
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
            },
        ],
        trimmedSearch: [(s) => [s.search], (search): string => search.trim()],
        isSearchActive: [
            (s) => [s.trimmedSearch, s.hasActiveFolder],
            (trimmedSearch, hasActiveFolder): boolean => trimmedSearch !== '' && hasActiveFolder,
        ],
        searchMatchesCurrentFolder: [
            (s) => [s.explorerSearchResults, s.explorerFolderPath],
            (explorerSearchResults, explorerFolderPath): boolean =>
                explorerSearchResults.folderPath === explorerFolderPath && explorerSearchResults.searchTerm !== '',
        ],
        shouldUseSearchRows: [
            (s) => [s.isSearchActive, s.searchMatchesCurrentFolder],
            (isSearchActive, searchMatchesCurrentFolder): boolean => isSearchActive && searchMatchesCurrentFolder,
        ],
        searchRows: [
            (s) => [s.explorerSearchResults, s.shouldUseSearchRows],
            ({ results }, shouldUseSearchRows): ExplorerRow[] => {
                if (!shouldUseSearchRows) {
                    return []
                }

                return [...(results || [])]
                    .sort(sortFilesAndFolders)
                    .map((entry) => ({ entry, depth: 0, isSearchResult: true }))
            },
        ],
        isLoadingCurrentFolder: [
            (s) => [s.hasActiveFolder, s.folderStates, s.explorerFolderPath],
            (hasActiveFolder, folderStates, explorerFolderPath): boolean =>
                hasActiveFolder ? folderStates[explorerFolderPath] === 'loading' : false,
        ],
        breadcrumbSegments: [
            (s) => [s.explorerFolderPath],
            (explorerFolderPath): string[] => splitPath(explorerFolderPath),
        ],
        parentBreadcrumbSegments: [
            (s) => [s.breadcrumbSegments],
            (breadcrumbSegments): string[] => breadcrumbSegments.slice(0, -1),
        ],
        parentFolderPath: [
            (s) => [s.parentBreadcrumbSegments],
            (parentBreadcrumbSegments): string => joinPath(parentBreadcrumbSegments),
        ],
        parentRow: [
            (s) => [s.hasActiveFolder, s.breadcrumbSegments, s.explorerFolderPath, s.parentFolderPath],
            (hasActiveFolder, breadcrumbSegments, explorerFolderPath, parentFolderPath): ExplorerRow | null => {
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
            },
        ],
        contentRows: [
            (s) => [s.shouldUseSearchRows, s.searchRows, s.rows],
            (shouldUseSearchRows, searchRows, rows): ExplorerRow[] => (shouldUseSearchRows ? searchRows : rows),
        ],
        displayRows: [
            (s) => [s.parentRow, s.contentRows, s.shouldUseSearchRows],
            (parentRow, contentRows, shouldUseSearchRows): ExplorerRow[] =>
                parentRow && !shouldUseSearchRows ? [parentRow, ...contentRows] : contentRows,
        ],
        isLoadingRows: [
            (s) => [s.isSearchActive, s.explorerSearchResultsLoading, s.isLoadingCurrentFolder],
            (isSearchActive, explorerSearchResultsLoading, isLoadingCurrentFolder): boolean =>
                isSearchActive ? explorerSearchResultsLoading : isLoadingCurrentFolder,
        ],
        rowGridClass: [
            (s) => [s.shouldUseSearchRows],
            (shouldUseSearchRows): string =>
                shouldUseSearchRows
                    ? 'grid grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)_200px_160px_48px]'
                    : 'grid grid-cols-[minmax(0,1fr)_200px_160px_48px]',
        ],
        highlightedFocusKey: [
            (s) => [s.displayRows, s.highlightedExplorerEntryPath],
            (displayRows, highlightedExplorerEntryPath): string | null => {
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
            },
        ],
        getEntryFolderLabel: [
            () => [],
            () =>
                (entry: FileSystemEntry): string => {
                    const segments = splitPath(entry.path)
                    if (segments.length <= 1) {
                        return 'Project root'
                    }
                    return joinPath(segments.slice(0, -1))
                },
        ],
        highlightSearchText: [
            (s) => [s.shouldUseSearchRows, s.trimmedSearch],
            (shouldUseSearchRows, trimmedSearch) =>
                (text: string): JSXElement | string => {
                    if (!shouldUseSearchRows || !trimmedSearch) {
                        return text
                    }
                    return <SearchHighlightMultiple string={text} substring={trimmedSearch} />
                },
        ],
        getParentRowFocusKey: [
            () => [],
            () =>
                (folderPath: string): string =>
                    `__parent-${folderPath || 'root'}-row`,
        ],
        renderCreatedBy: [
            (s) => [s.users],
            (users) =>
                (entry: FileSystemEntry): JSXElement => {
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
                },
        ],
        renderCreatedAt: [
            () => [],
            () =>
                (entry: FileSystemEntry): string =>
                    entry.created_at ? dayjs(entry.created_at).format('MMM D, YYYY') : '—',
        ],
    }),
    subscriptions(({ actions, values }) => ({
        activeExplorerFolderPath: (activeExplorerFolderPath) => {
            if (activeExplorerFolderPath === null) {
                return
            }
            if (
                !values.folders[activeExplorerFolderPath] &&
                values.folderStates[activeExplorerFolderPath] !== 'loading'
            ) {
                actions.loadFolder(activeExplorerFolderPath)
            }
        },
    })),
])
