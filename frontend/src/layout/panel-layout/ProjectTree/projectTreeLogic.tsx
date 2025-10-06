import { actions, afterMount, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { IconPlus } from '@posthog/icons'
import { Link, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { LemonTreeSelectMode, TreeDataItem, TreeMode, TreeTableViewKeys } from 'lib/lemon-ui/LemonTree/LemonTree'
import { urls } from 'scenes/urls'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { PAGINATION_LIMIT, projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { ProjectTreeRef } from '~/types'

import { panelLayoutLogic } from '../panelLayoutLogic'
import type { projectTreeLogicType } from './projectTreeLogicType'
import {
    convertFileSystemEntryToTreeDataItem,
    findInProjectTree,
    formatUrlAsName,
    joinPath,
    sortFilesAndFolders,
    splitPath,
    splitProtocolPath,
} from './utils'

export type ProjectTreeSortMethod = 'folder' | 'recent'

export interface RecentResults {
    results: FileSystemEntry[]
    startTime: string | null
    endTime: string | null
    hasMore: boolean
}

export interface SearchResults {
    searchTerm: string
    results: FileSystemEntry[]
    hasMore: boolean
    lastCount: number
}

export interface ProjectTreeLogicProps {
    key: string
    defaultSortMethod?: ProjectTreeSortMethod
    defaultOnlyFolders?: boolean
    root?: string
    includeRoot?: boolean
    hideFolders?: string[]
}

export const projectTreeLogic = kea<projectTreeLogicType>([
    path(['layout', 'navigation-3000', 'components', 'projectTreeLogic']),
    props({} as ProjectTreeLogicProps),
    key((props) => props.key),
    connect(() => ({
        values: [
            breadcrumbsLogic,
            ['projectTreeRef', 'appBreadcrumbs', 'sceneBreadcrumbs'],
            projectTreeDataLogic,
            [
                'folders',
                'folderStates',
                'folderLoadOffset',
                'users',
                'viableItems',
                'viableItemsById',
                'sortedItems',
                'loadingPaths',
                'lastNewFolder',
                'getStaticTreeItems',
                'shortcutData',
            ],
        ],
        actions: [
            panelLayoutLogic,
            ['setActivePanelIdentifier', 'resetPanelLayout'],
            projectTreeDataLogic,
            [
                'loadFolder',
                'loadFolderIfNotLoaded',
                'loadFolderStart',
                'loadFolderSuccess',
                'addLoadedUsers',
                'addLoadedResults',
                'createSavedItem',
                'deleteSavedItem',
                'deleteTypeAndRef',
                'movedItem',
                'queueAction',
                'deleteItem',
                'moveItem',
                'linkItem',
            ],
        ],
    })),
    actions({
        addFolder: (folder: string, editAfter = true, callback?: (folder: string) => void) => ({
            folder,
            editAfter,
            callback,
        }),
        setExpandedFolders: (folderIds: string[]) => ({ folderIds }),
        setExpandedSearchFolders: (folderIds: string[]) => ({ folderIds }),
        setLastViewedId: (id: string) => ({ id }),
        toggleFolderOpen: (folderId: string, isExpanded: boolean) => ({ folderId, isExpanded }),
        setHelpNoticeVisibility: (visible: boolean) => ({ visible }),
        rename: (value: string, item: FileSystemEntry) => ({ value, item }),
        createFolder: (parentPath: string, editAfter = true, callback?: (folder: string) => void) => ({
            parentPath,
            editAfter,
            callback,
        }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        clearSearch: true,
        loadSearchResults: (searchTerm: string, offset = 0) => ({ searchTerm, offset }),
        loadRecentResults: (type: 'start' | 'end') => ({ type }),
        assureVisibility: (projectTreeRef: ProjectTreeRef) => ({ projectTreeRef }),
        onItemChecked: (id: string, checked: boolean, shift: boolean) => ({ id, checked, shift }),
        setLastCheckedItem: (id: string, checked: boolean, shift: boolean) => ({ id, checked, shift }),
        setCheckedItems: (checkedItems: Record<string, boolean>) => ({ checkedItems }),
        expandProjectFolder: (path: string) => ({ path }),
        moveCheckedItems: (path: string) => ({ path }),
        linkCheckedItems: (path: string) => ({ path }),
        deleteCheckedItems: true,
        checkSelectedFolders: true,
        scrollToView: (item: FileSystemEntry) => ({ item }),
        clearScrollTarget: true,
        setEditingItemId: (id: string) => ({ id }),
        setSortMethod: (sortMethod: ProjectTreeSortMethod) => ({ sortMethod }),
        setOnlyFolders: (onlyFolders: boolean) => ({ onlyFolders }),
        setSelectMode: (selectMode: LemonTreeSelectMode) => ({ selectMode }),
        setTreeTableColumnSizes: (sizes: number[]) => ({ sizes }),
        setProjectTreeMode: (mode: TreeMode) => ({ mode }),
    }),
    loaders(({ actions, values }) => ({
        searchResults: [
            { searchTerm: '', results: [], hasMore: false, lastCount: 0 } as SearchResults,
            {
                loadSearchResults: async ({ searchTerm, offset }, breakpoint) => {
                    await breakpoint(250)
                    const response = await api.fileSystem.list({
                        search: searchTerm,
                        offset,
                        limit: PAGINATION_LIMIT + 1,
                        orderBy: values.sortMethod === 'recent' ? '-created_at' : undefined,
                        notType: values.sortMethod === 'recent' ? 'folder' : undefined,
                    })
                    breakpoint()
                    const results = [
                        ...(offset > 0 && searchTerm === values.searchResults.searchTerm
                            ? values.searchResults.results
                            : []),
                        ...response.results.slice(0, PAGINATION_LIMIT),
                    ]
                    if (response.users?.length > 0) {
                        actions.addLoadedUsers(response.users)
                    }
                    actions.addLoadedResults(response as any as SearchResults)
                    return {
                        searchTerm,
                        results: values.sortMethod === 'recent' ? results : results.sort(sortFilesAndFolders),
                        hasMore: response.results.length > PAGINATION_LIMIT,
                        lastCount: Math.min(response.results.length, PAGINATION_LIMIT),
                    }
                },
            },
        ],
        recentResults: [
            { results: [], hasMore: false, startTime: null, endTime: null } as RecentResults,
            {
                loadRecentResults: async ({ type }, breakpoint) => {
                    await breakpoint(250)
                    const params = {
                        orderBy: '-created_at',
                        notType: 'folder',
                        limit: PAGINATION_LIMIT + 1,
                        createdAtGt:
                            type === 'start' && values.recentResults.startTime
                                ? values.recentResults.startTime
                                : undefined,
                        createdAtLt:
                            type === 'end' && values.recentResults.endTime ? values.recentResults.endTime : undefined,
                    }
                    const response = await api.fileSystem.list(params)
                    const returnedResults = response.results.slice(0, PAGINATION_LIMIT)
                    const hasMore = response.results.length > PAGINATION_LIMIT
                    breakpoint()
                    const seenIds = new Set()
                    const results = [...values.recentResults.results, ...returnedResults]
                        .filter((item) => {
                            if (seenIds.has(item.id)) {
                                return false
                            }
                            seenIds.add(item.id)
                            return true
                        })
                        .sort((a, b) => {
                            return new Date(b.created_at ?? '').getTime() - new Date(a.created_at ?? '').getTime()
                        })
                    if (response.users?.length > 0) {
                        actions.addLoadedUsers(response.users)
                    }
                    actions.addLoadedResults(response as any as RecentResults)
                    return {
                        results,
                        hasMore,
                        startTime: response.results[0]?.created_at ?? null,
                        endTime: response.results[response.results.length - 1]?.created_at ?? null,
                    }
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                clearSearch: () => '',
            },
        ],
        searchResults: [
            { searchTerm: '', results: [], hasMore: false, lastCount: 0 } as SearchResults,
            {
                movedItem: (state, { newPath, item }) => {
                    if (state.searchTerm && state.results.length > 0) {
                        const newResults = state.results.map((result) => {
                            if (result.id === item.id) {
                                return { ...item, path: newPath }
                            }
                            return result
                        })
                        return { ...state, results: newResults }
                    }
                    return state
                },
                deleteSavedItem: (state, { savedItem }) => {
                    if (state.searchTerm && state.results.length > 0) {
                        const newResults = state.results.filter((result) => result.id !== savedItem.id)
                        return { ...state, results: newResults }
                    }
                    return state
                },
                deleteTypeAndRef: (state, { type, ref }) => {
                    return {
                        ...state,
                        results: state.results.filter(
                            (file) =>
                                (type.endsWith('/') ? !file.type?.startsWith(type) : file.type !== type) ||
                                file.ref !== ref
                        ),
                    }
                },
                addLoadedResults: (state, { results }) => {
                    const newIdsSet = new Set(results.results.map((file) => file.id))
                    const hasAnyNewIds = state.results.some((file) => newIdsSet.has(file.id))
                    if (hasAnyNewIds) {
                        const newResults = state.results.map((result) => {
                            if (newIdsSet.has(result.id)) {
                                const file = results.results.find((file) => file.id === result.id)
                                return { ...result, ...file }
                            }
                            return result
                        })
                        return { ...state, results: newResults }
                    }
                    return state
                },
            },
        ],
        recentResults: [
            { results: [], hasMore: false, startTime: null, endTime: null } as RecentResults,
            {
                movedItem: (state, { newPath, item }) => {
                    if (state.results.length > 0) {
                        const newResults = state.results.map((result) => {
                            if (result.id === item.id) {
                                return { ...item, path: newPath }
                            }
                            return result
                        })
                        return { ...state, results: newResults }
                    }
                    return state
                },
                deleteSavedItem: (state, { savedItem }) => {
                    if (state.results.length > 0) {
                        const newResults = state.results.filter((result) => result.id !== savedItem.id)
                        return { ...state, results: newResults }
                    }
                    return state
                },
                deleteTypeAndRef: (state, { type, ref }) => {
                    return {
                        ...state,
                        results: state.results.filter(
                            (file) =>
                                (type.endsWith('/') ? !file.type?.startsWith(type) : file.type !== type) ||
                                file.ref !== ref
                        ),
                    }
                },
                createSavedItem: (state, { savedItem }) => {
                    if (state.results.find((result) => result.id === savedItem.id)) {
                        return {
                            ...state,
                            results: state.results.map((result) => (result.id === savedItem.id ? savedItem : result)),
                        }
                    } else if (savedItem.created_at && savedItem.type !== 'folder') {
                        const newResults = [...state.results, savedItem].sort((a, b) => {
                            return new Date(b.created_at ?? '').getTime() - new Date(a.created_at ?? '').getTime()
                        })
                        return { ...state, results: newResults }
                    }
                    return state
                },
                addLoadedResults: (state, { results }) => {
                    const newIdsSet = new Set(results.results.map((file) => file.id))
                    const hasAnyNewIds = state.results.some((file) => newIdsSet.has(file.id))
                    if (hasAnyNewIds) {
                        const newResults = state.results.map((result) => {
                            if (newIdsSet.has(result.id)) {
                                const file = results.results.find((file) => file.id === result.id)
                                return { ...result, ...file }
                            }
                            return result
                        })
                        return { ...state, results: newResults }
                    }
                    return state
                },
            },
        ],
        expandedFolders: [
            [props.root] as string[],
            {
                setExpandedFolders: (_, { folderIds }) => folderIds,
            },
        ],
        expandedSearchFolders: [
            ['/', 'project://', 'project://Unfiled'] as string[],
            {
                setExpandedSearchFolders: (_, { folderIds }) => folderIds,
                loadSearchResultsSuccess: (state, { searchResults: { results, lastCount } }) => {
                    const folders: Record<string, boolean> = state.reduce(
                        (acc: Record<string, boolean>, folderId) => {
                            acc[folderId] = true
                            return acc
                        },
                        { 'project://Unfiled': true }
                    )

                    for (const entry of results.slice(-lastCount)) {
                        const splits = splitPath(entry.path)
                        for (let i = 1; i < splits.length; i++) {
                            folders['project://' + joinPath(splits.slice(0, i))] = true
                        }
                    }
                    return Object.keys(folders)
                },
            },
        ],
        lastViewedId: [
            '',
            {
                setLastViewedId: (_, { id }) => id,
            },
        ],
        helpNoticeVisible: [
            true,
            {
                setHelpNoticeVisibility: (_, { visible }) => visible,
            },
        ],
        checkedItems: [
            {} as Record<string, boolean>,
            {
                setCheckedItems: (_, { checkedItems }) => checkedItems,
            },
        ],
        lastCheckedItem: [
            null as { id: string; checked: boolean; shift: boolean } | null,
            {
                setLastCheckedItem: (_, { id, checked, shift }) => ({ id, checked, shift }),
            },
        ],
        scrollTargetId: [
            '' as string,
            {
                scrollToView: (_, { item }) =>
                    item.type === 'folder' ? `project://${item.path}` : `project/${item.id}`,
                clearScrollTarget: () => '',
            },
        ],
        editingItemId: [
            '',
            {
                setEditingItemId: (_, { id }) => id,
            },
        ],
        sortMethod: [
            'folder' as ProjectTreeSortMethod,
            {
                setSortMethod: (_, { sortMethod }) => sortMethod,
            },
        ],
        onlyFolders: [
            false as boolean,
            {
                setOnlyFolders: (_, { onlyFolders }) => onlyFolders,
            },
        ],
        selectMode: [
            'default' as LemonTreeSelectMode,
            {
                setSelectMode: (_, { selectMode }) => selectMode,
            },
        ],
        treeTableColumnSizes: [
            [350, 200, 200, 200] as number[],
            { persist: true },
            {
                setTreeTableColumnSizes: (_, { sizes }) => sizes,
            },
        ],
        projectTreeMode: [
            'tree' as TreeMode,
            {
                setProjectTreeMode: (_, { mode }) => mode,
            },
        ],
    })),
    selectors({
        projectTree: [
            (s) => [s.viableItems, s.folderStates, s.checkedItems, s.users, s.onlyFolders],
            (viableItems, folderStates, checkedItems, users, onlyFolders): TreeDataItem[] => {
                const children = convertFileSystemEntryToTreeDataItem({
                    imports: viableItems.map((i) => ({ ...i, protocol: 'project://' })),
                    folderStates,
                    checkedItems,
                    root: 'project://',
                    users,
                    disabledReason: onlyFolders
                        ? (item) => (item.type !== 'folder' ? 'Only folders can be selected' : undefined)
                        : undefined,
                })
                return children
            },
        ],
        recentTreeItems: [
            (s) => [s.recentResults, s.recentResultsLoading, s.folderStates, s.checkedItems, s.users],
            (recentResults, recentResultsLoading, folderStates, checkedItems, users): TreeDataItem[] => {
                const results = convertFileSystemEntryToTreeDataItem({
                    imports: recentResults.results.map((i) => ({ ...i, protocol: 'project://' })),
                    folderStates,
                    checkedItems,
                    root: 'project://',
                    disableFolderSelect: true,
                    recent: true,
                    users,
                })
                if (recentResultsLoading) {
                    results.push({
                        id: `recent-loading/`,
                        name: 'Loading...',
                        displayName: <>Loading...</>,
                        icon: <Spinner />,
                        disableSelect: true,
                        type: 'loading-indicator',
                    })
                } else if (recentResults.hasMore) {
                    results.push({
                        id: `recent-load-more/`,
                        name: 'Load more...',
                        displayName: <>Load more...</>,
                        icon: <IconPlus />,
                        disableSelect: true,
                        onClick: () => projectTreeLogic.actions.loadRecentResults('end'),
                    })
                }
                return results
            },
        ],
        searchTreeItems: [
            (s) => [
                s.searchResults,
                s.searchResultsLoading,
                s.folderStates,
                s.checkedItems,
                s.sortMethod,
                s.onlyFolders,
                s.users,
            ],
            (
                searchResults,
                searchResultsLoading,
                folderStates,
                checkedItems,
                sortMethod,
                onlyFolders,
                users
            ): TreeDataItem[] => {
                const results = convertFileSystemEntryToTreeDataItem({
                    imports: searchResults.results.map((i) => ({ ...i, protocol: 'project://' })),
                    folderStates,
                    checkedItems,
                    root: 'project://',
                    searchTerm: searchResults.searchTerm,
                    disableFolderSelect: true,
                    recent: sortMethod === 'recent',
                    users,
                    disabledReason: onlyFolders
                        ? (item) => (item.type !== 'folder' ? 'Only folders can be selected' : undefined)
                        : undefined,
                })
                if (searchResultsLoading) {
                    results.push({
                        id: `search-loading/`,
                        name: 'Loading...',
                        displayName: <>Loading...</>,
                        icon: <Spinner />,
                        disableSelect: true,
                        type: 'loading-indicator',
                    })
                } else if (searchResults.hasMore) {
                    results.push({
                        id: `search-load-more/${searchResults.searchTerm}`,
                        name: 'Load more...',
                        displayName: <>Load more...</>,
                        icon: <IconPlus />,
                        disableSelect: true,
                        onClick: () =>
                            projectTreeLogic.actions.loadSearchResults(
                                searchResults.searchTerm,
                                searchResults.results.length
                            ),
                    })
                }
                return results
            },
        ],
        projectTreeItems: [
            (s) => [s.searchTerm, s.searchTreeItems, s.projectTree, s.loadingPaths, s.recentTreeItems, s.sortMethod],
            (searchTerm, searchTreeItems, projectTree, loadingPaths, recentTreeItems, sortMethod): TreeDataItem[] => {
                if (searchTerm) {
                    return searchTreeItems
                }
                if (sortMethod === 'recent') {
                    return recentTreeItems
                }
                if (loadingPaths[''] && projectTree.length === 0) {
                    return [
                        {
                            id: `folder-loading/`,
                            name: 'Loading...',
                            icon: <Spinner />,
                            type: 'loading-indicator',
                        },
                    ]
                }
                return projectTree
            },
        ],
        fullFileSystem: [
            (s) => [
                s.searchTerm,
                s.searchTreeItems,
                s.searchResultsLoading,
                s.projectTree,
                s.loadingPaths,
                s.recentTreeItems,
                s.recentResultsLoading,
                s.sortMethod,
                s.onlyFolders,
                s.getStaticTreeItems,
            ],
            (
                searchTerm,
                searchTreeItems,
                searchResultsLoading,
                projectTree,
                loadingPaths,
                recentTreeItems,
                recentResultsLoading,
                sortMethod,
                onlyFolders,
                getStaticTreeItems
            ): TreeDataItem[] => {
                const folderLoading = [
                    {
                        id: `folder-loading/`,
                        name: 'Loading...',
                        icon: <Spinner />,
                        type: 'loading-indicator',
                    },
                ]
                const root: TreeDataItem[] = [
                    {
                        id: 'project://',
                        name: 'project://',
                        displayName: <>Project</>,
                        record: { type: 'folder', protocol: 'project://', path: '' },
                        children: searchTerm
                            ? searchResultsLoading && searchTreeItems.length === 0
                                ? folderLoading
                                : searchTreeItems
                            : sortMethod === 'recent'
                              ? recentResultsLoading && recentTreeItems.length === 0
                                  ? folderLoading
                                  : recentTreeItems
                              : loadingPaths[''] && projectTree.length === 0
                                ? folderLoading
                                : projectTree,
                    } as TreeDataItem,
                    ...getStaticTreeItems(searchTerm, onlyFolders),
                ]
                return root
            },
        ],
        fullFileSystemFiltered: [
            (s) => [
                s.fullFileSystem,
                s.searchTerm,
                (_, props) => props.root,
                (_, props) => props.includeRoot,
                (_, props) => props.hideFolders,
            ],
            (fullFileSystem, searchTerm, root, includeRoot, hideFolders): TreeDataItem[] => {
                let firstFolders = fullFileSystem

                // Filter out folders specified in hideFolders prop
                if (hideFolders && hideFolders.length > 0) {
                    firstFolders = firstFolders.filter((item) => !hideFolders.includes(item.id))
                }

                const rootFolders = root ? splitPath(root) : []
                const rootWithProtocol =
                    rootFolders.length > 0 && rootFolders[0].endsWith(':') && root.startsWith(`${rootFolders[0]}//`)

                if (rootWithProtocol) {
                    const protocol = rootFolders[0] + '//'
                    const ref = joinPath(rootFolders.slice(1))
                    const firstFolder = fullFileSystem.find((item) => item.id === protocol)
                    if (firstFolder) {
                        if (ref) {
                            const found = findInProjectTree(`${protocol}${ref}`, firstFolder.children ?? [])
                            firstFolders = found?.children ?? []
                        } else {
                            firstFolders = firstFolder.children ?? []
                        }
                    } else {
                        firstFolders = []
                    }
                }

                function addRoot(tree: TreeDataItem[]): TreeDataItem[] {
                    if (includeRoot) {
                        return [
                            {
                                id: root,
                                name: formatUrlAsName(root),
                                displayName: <>{formatUrlAsName(root)}</>,
                                record: {
                                    type: 'folder',
                                    path: rootWithProtocol ? joinPath(rootFolders.splice(2)) : root,
                                },
                                children: tree,
                            },
                        ] as TreeDataItem[]
                    }
                    return tree
                }

                // no client side filtering under project://
                if (!searchTerm || !root || root.startsWith('project://')) {
                    return addRoot(firstFolders)
                }
                const term = searchTerm.toLowerCase()

                const filterTree = (nodes: TreeDataItem[]): TreeDataItem[] =>
                    nodes.reduce<TreeDataItem[]>((acc, node) => {
                        // Do not do client side filtering under the project:// path if looking at the full tree
                        if (node.id === 'project://') {
                            acc.push(node)
                            return acc
                        }

                        const children = node.children ? filterTree(node.children) : undefined
                        const path =
                            typeof node.record === 'object' && node.record && 'path' in node.record
                                ? ((node.record as { path?: string }).path ?? '')
                                : ''
                        const matches = path.toLowerCase().includes(term)

                        if (matches || (children && children.length)) {
                            acc.push({ ...node, children })
                        }
                        return acc
                    }, [])

                return addRoot(filterTree(firstFolders))
            },
        ],
        treeTableColumnOffsets: [
            (s) => [s.treeTableColumnSizes],
            (sizes): number[] => sizes.map((_, index) => sizes.slice(0, index).reduce((acc, s) => acc + s, 0)),
        ],
        // TODO: use treeData + some other logic to determine the keys
        treeTableKeys: [
            (s) => [s.treeTableColumnSizes, s.treeTableColumnOffsets, s.sortMethod, s.users, s.projectTreeMode],
            (sizes, offsets, sortMethod, users, projectTreeMode): TreeTableViewKeys => ({
                headers: [
                    {
                        key: 'name',
                        title: 'Name',
                        tooltip: (value: string) => value,
                        width: sizes[0],
                        offset: offsets[0],
                    },
                    {
                        key: 'record.meta.created_at',
                        title: 'Created at',
                        formatComponent: (created_at) =>
                            created_at ? (
                                <span className="text-muted text-xs">{dayjs(created_at).fromNow()}</span>
                            ) : (
                                '-'
                            ),
                        formatString: (created_at) => (created_at ? dayjs(created_at).fromNow() : '-'),
                        tooltip: (created_at) => (created_at ? dayjs(created_at).format('MMM D, YYYY HH:mm:ss') : ''),
                        width: sizes[1],
                        offset: offsets[1],
                    },
                    {
                        key: 'record.meta.created_by',
                        title: 'Created by',
                        formatComponent: (created_by) =>
                            created_by && users[created_by] ? (
                                <Link
                                    to={urls.personByDistinctId(users[created_by].distinct_id)}
                                    onClick={(e) => {
                                        e.preventDefault()
                                        e.stopPropagation()
                                        router.actions.push(urls.personByDistinctId(users[created_by].distinct_id))
                                        if (projectTreeMode === 'table') {
                                            projectTreeLogic.actions.setProjectTreeMode('tree')
                                        }
                                    }}
                                >
                                    <ProfilePicture user={users[created_by]} size="sm" className="mr-1" />
                                    <span>
                                        {users[created_by].first_name} {users[created_by].last_name}
                                    </span>
                                </Link>
                            ) : (
                                '-'
                            ),
                        formatString: (created_by) =>
                            created_by && users[created_by]
                                ? `${users[created_by].first_name} ${users[created_by].last_name}`
                                : '-',
                        width: sizes[2],
                        offset: offsets[2],
                    },
                    ...(sortMethod === 'recent'
                        ? [
                              {
                                  key: 'record.path',
                                  title: 'Folder',
                                  formatString: (value: string) =>
                                      value ? joinPath(splitPath(value).slice(0, -1)) : '',
                                  tooltip: (value: string) => (value ? joinPath(splitPath(value).slice(0, -1)) : ''),
                                  width: sizes[3] || 200,
                                  offset: offsets[3],
                              },
                          ]
                        : []),
                ],
            }),
        ],
        treeTableTotalWidth: [(s) => [s.treeTableColumnSizes], (sizes): number => sizes.reduce((acc, s) => acc + s, 0)],
        checkedItemCountNumeric: [
            (s) => [s.checkedItems],
            (checkedItems): number => Object.values(checkedItems).filter((v) => !!v).length,
        ],
        checkedItemsCount: [
            (s) => [s.checkedItems, s.viableItemsById],
            (checkedItems, viableItemsById): string => {
                let hasFolder = false
                let sum = 0
                for (const [key, value] of Object.entries(checkedItems)) {
                    if (value) {
                        sum += 1
                        if (viableItemsById[key]?.type === 'folder') {
                            hasFolder = true
                        }
                    }
                }

                return `${sum}${hasFolder ? '+' : ''}`
            },
        ],
        checkedItemsArray: [
            (s) => [s.checkedItems, s.viableItemsById],
            (checkedItems, viableItemsById): FileSystemEntry[] => {
                return Object.entries(checkedItems)
                    .filter(([_, checked]) => checked)
                    .map(([id]) => viableItemsById[id])
                    .filter(Boolean)
            },
        ],
    }),
    listeners(({ actions, values, key }) => ({
        setActivePanelIdentifier: () => {
            // clear search term when changing panel
            if (values.searchTerm !== '') {
                actions.clearSearch()
            }
            if (values.projectTreeMode !== 'tree') {
                actions.setProjectTreeMode('tree')
            }
        },
        resetPanelLayout: () => {
            if (values.projectTreeMode !== 'tree') {
                actions.setProjectTreeMode('tree')
            }
        },
        loadFolderSuccess: ({ folder }) => {
            if (folder === '') {
                const rootItems = values.folders['']
                if (rootItems.length < 5) {
                    actions.toggleFolderOpen('project://Unfiled', true)
                }
            }
            actions.checkSelectedFolders()
        },
        createSavedItem: () => {
            actions.checkSelectedFolders()
        },
        loadSearchResultsSuccess: () => {
            actions.checkSelectedFolders()
        },
        deleteSavedItem: () => {
            actions.checkSelectedFolders()
        },
        movedItem: () => {
            actions.checkSelectedFolders()
        },
        checkSelectedFolders: () => {
            // Select items added into folders that are selected
            const checkedItems = values.checkedItems
            const toCheck = []
            let checkingFolder: string | null = null
            for (const item of values.sortedItems) {
                if (checkingFolder === null) {
                    if (item.type === 'folder' && checkedItems[`project://${item.path}`]) {
                        checkingFolder = item.path
                    }
                } else {
                    if (item.path.startsWith(checkingFolder + '/')) {
                        if (item.type === 'folder') {
                            if (!checkedItems[`project://${item.path}`]) {
                                toCheck.push(`project://${item.path}`)
                            }
                        } else {
                            if (!checkedItems[`project/${item.id}`]) {
                                toCheck.push(`project/${item.id}`)
                            }
                        }
                    } else {
                        checkingFolder = null
                        if (item.type === 'folder' && checkedItems[`project://${item.path}`]) {
                            checkingFolder = item.path
                        }
                    }
                }
            }
            const toDelete = new Set<string>()
            for (const itemId of Object.keys(checkedItems)) {
                if (!values.viableItemsById[itemId]) {
                    toDelete.add(itemId)
                }
            }
            if (toCheck.length > 0 || toDelete.size > 0) {
                actions.setCheckedItems({
                    ...(toDelete.size === 0
                        ? checkedItems
                        : Object.fromEntries(Object.entries(checkedItems).filter((kv) => !toDelete.has(kv[0])))),
                    ...Object.fromEntries(toCheck.map((item) => [item, true])),
                })
            }
        },
        expandProjectFolder: ({ path }) => {
            const expandedSet = new Set(values.expandedFolders)
            const allFolders = splitPath(path).slice(0, -1)
            const allFullFolders = allFolders.map((_, index) => joinPath(allFolders.slice(0, index + 1)))
            const nonExpandedFolders = allFullFolders.filter((f) => !expandedSet.has('project://' + f))
            for (const folder of nonExpandedFolders) {
                if (values.folderStates[folder] !== 'loaded' && values.folderStates[folder] !== 'loading') {
                    actions.loadFolder(folder)
                }
            }
            actions.setExpandedFolders([...values.expandedFolders, ...nonExpandedFolders.map((f) => 'project://' + f)])
        },
        onItemChecked: ({ id, checked, shift }) => {
            const {
                sortedItems,
                searchResults,
                sortMethod,
                recentResults,
                viableItemsById,
                lastCheckedItem,
                checkedItems: prevChecked,
            } = values
            const clickedItem = viableItemsById[id]
            if (!clickedItem) {
                // should never happen
                return
            }
            const isSearching = !!values.searchTerm
            const shownItems = isSearching
                ? searchResults.results
                : sortMethod === 'recent'
                  ? recentResults.results
                  : sortedItems

            const checkedItems = { ...prevChecked }

            const itemKey = (item: FileSystemEntry): string =>
                item.type === 'folder' ? `project://${item.path}` : `project/${item.id}`

            const markItem = (item: FileSystemEntry, value: boolean): void => {
                checkedItems[itemKey(item)] = value
            }

            const markFolderContents = (folder: FileSystemEntry, value: boolean): void => {
                if (isSearching) {
                    return
                }
                const startIdx = shownItems.findIndex((i) => i.id === folder.id)
                for (let i = startIdx + 1; i < shownItems.length; i++) {
                    const entry = shownItems[i]
                    if (!entry.path.startsWith(folder.path + '/')) {
                        // left the folder
                        break
                    }
                    markItem(entry, value)
                }
            }

            const applyToItem = (item: FileSystemEntry): void => {
                markItem(item, !!checked)
                if (item.type === 'folder') {
                    markFolderContents(item, !!checked)
                }
            }

            if (shift && lastCheckedItem) {
                const prevIdx = shownItems.findIndex((it) => itemKey(it) === lastCheckedItem.id)
                const currIdx = shownItems.findIndex((it) => it.id === clickedItem.id)
                if (prevIdx !== -1 && currIdx !== -1) {
                    const [start, end] = [Math.min(prevIdx, currIdx), Math.max(prevIdx, currIdx)]
                    for (let i = start; i <= end; i++) {
                        applyToItem(shownItems[i])
                    }
                } else if (currIdx !== -1) {
                    applyToItem(shownItems[currIdx])
                }
            } else {
                applyToItem(clickedItem)
            }

            actions.setLastCheckedItem(id, checked, shift)
            actions.setCheckedItems(checkedItems)

            // If any items are checked, set the select mode to multi
            // We don't do the inverse because we don't want to set the select mode to default when deselecting all
            if (Object.values(checkedItems).some((v) => !!v)) {
                actions.setSelectMode('multi')
            }
        },
        moveCheckedItems: ({ path }) => {
            const { checkedItems } = values
            let skipInFolder: string | null = null
            for (const item of values.sortedItems) {
                if (skipInFolder !== null) {
                    if (item.path.startsWith(skipInFolder + '/')) {
                        continue
                    } else {
                        skipInFolder = null
                    }
                }
                const itemId = item.type === 'folder' ? `project://${item.path}` : `project/${item.id}`
                if (checkedItems[itemId]) {
                    actions.moveItem(item, joinPath([...splitPath(path), ...splitPath(item.path).slice(-1)]), true, key)
                    if (item.type === 'folder') {
                        skipInFolder = item.path
                    }
                }
            }
        },
        linkCheckedItems: ({ path }) => {
            const { checkedItems } = values
            let skipInFolder: string | null = null
            for (const item of values.sortedItems) {
                if (skipInFolder !== null) {
                    if (item.path.startsWith(skipInFolder + '/')) {
                        continue
                    } else {
                        skipInFolder = null
                    }
                }
                const itemId = item.type === 'folder' ? `project://${item.path}` : `project/${item.id}`
                if (checkedItems[itemId]) {
                    actions.linkItem(
                        item.path,
                        joinPath([...splitPath(path), ...splitPath(item.path).slice(-1)]),
                        true,
                        key
                    )
                    if (item.type === 'folder') {
                        skipInFolder = item.path
                    }
                }
            }
        },
        deleteCheckedItems: () => {
            const { checkedItems } = values
            let skipInFolder: string | null = null
            for (const item of values.sortedItems) {
                if (skipInFolder !== null) {
                    if (item.path.startsWith(skipInFolder + '/')) {
                        continue
                    } else {
                        skipInFolder = null
                    }
                }
                const itemId = item.type === 'folder' ? `project://${item.path}` : `project/${item.id}`
                if (checkedItems[itemId]) {
                    actions.deleteItem(item, key)
                    if (item.type === 'folder') {
                        skipInFolder = item.path
                    }
                }
            }
        },
        addFolder: ({ folder, editAfter, callback }) => {
            // Like Mac, we don't allow duplicate folder names
            // So we need to increment the folder name until we find a unique one
            let folderName = folder
            let counter = 2
            while (values.viableItems.find((item) => item.path === folderName && item.type === 'folder')) {
                folderName = `${folder} ${counter}`
                counter++
            }

            actions.queueAction(
                {
                    type: 'create',
                    item: { id: `project/${folderName}`, path: folderName, type: 'folder' },
                    path: folderName,
                    newPath: folderName,
                },
                key
            )

            // Always set the editing item ID after a short delay to ensure the folder is in the DOM
            if (editAfter) {
                setTimeout(() => {
                    actions.setEditingItemId(`project://${folderName}`)
                }, 50)
            }
            callback?.(folderName)
        },
        toggleFolderOpen: ({ folderId }) => {
            if (values.searchTerm) {
                if (values.expandedSearchFolders.find((f) => f === folderId)) {
                    actions.setExpandedSearchFolders(values.expandedSearchFolders.filter((f) => f !== folderId))
                } else {
                    actions.setExpandedSearchFolders([...values.expandedSearchFolders, folderId])
                }
            } else {
                if (values.expandedFolders.find((f) => f === folderId)) {
                    actions.setExpandedFolders(values.expandedFolders.filter((f) => f !== folderId))
                } else {
                    actions.setExpandedFolders([...values.expandedFolders, folderId])
                    actions.loadFolderIfNotLoaded(folderId)
                }
            }
        },
        loadFolderIfNotLoaded: ({ folderId }) => {
            if (folderId.startsWith('shortcuts://')) {
                const [, path] = splitProtocolPath(folderId)
                const firstFolder = splitPath(path)[0]

                const shortcut = values.shortcutData.find((s) => s.path === firstFolder && s.type === 'folder')
                if (shortcut?.ref) {
                    actions.loadFolderIfNotLoaded('project://' + shortcut.ref)
                }
            }

            if (values.folderStates[folderId] !== 'loaded' && values.folderStates[folderId] !== 'loading') {
                const folder = findInProjectTree(folderId, values.projectTree)
                if (folder) {
                    actions.loadFolder(folder.record?.path)
                } else if (folderId.startsWith('project://')) {
                    actions.loadFolder(folderId.slice('project://'.length))
                }
            }
        },
        rename: ({ value, item }) => {
            const splits = splitPath(item.path)
            if (splits.length > 0) {
                if (value) {
                    actions.moveItem(item, joinPath([...splits.slice(0, -1), value]), false, key)
                    actions.setEditingItemId('')
                }
            }
        },
        createFolder: ({ parentPath, editAfter, callback }) => {
            const parentSplits = parentPath ? splitPath(parentPath) : []
            const newPath = joinPath([...parentSplits, 'Untitled folder'])
            actions.addFolder(newPath, editAfter, callback)
        },
        setSearchTerm: ({ searchTerm }) => {
            actions.loadSearchResults(searchTerm)
        },
        setSortMethod: ({ sortMethod }) => {
            if (values.searchTerm) {
                actions.loadSearchResults(values.searchTerm, 0)
            }
            if (sortMethod === 'recent' && !values.recentResultsLoading) {
                actions.loadRecentResults('start')
            }
        },
        assureVisibility: async ({ projectTreeRef }, breakpoint) => {
            if (projectTreeRef) {
                if (projectTreeRef.type === 'folder' && projectTreeRef.ref) {
                    actions.expandProjectFolder(projectTreeRef.ref)
                    const item = values.viableItems.find(
                        (item) => item.type === 'folder' && item.path === projectTreeRef.ref
                    )
                    if (item) {
                        actions.scrollToView(item)
                    }
                    return
                }

                const treeItem = projectTreeRef.type.endsWith('/')
                    ? values.viableItems.find(
                          (item) => item.type?.startsWith(projectTreeRef.type) && item.ref === projectTreeRef.ref
                      )
                    : values.viableItems.find(
                          (item) => item.type === projectTreeRef.type && item.ref === projectTreeRef.ref
                      )
                let path: string | undefined
                if (treeItem) {
                    path = treeItem.path
                } else if (projectTreeRef.ref !== null) {
                    const resp = await api.fileSystem.list(
                        projectTreeRef.type.endsWith('/')
                            ? { ref: projectTreeRef.ref, type__startswith: projectTreeRef.type }
                            : { ref: projectTreeRef.ref, type: projectTreeRef.type }
                    )
                    breakpoint() // bail if we opened some other item in the meanwhile
                    if (resp.users?.length > 0) {
                        actions.addLoadedUsers(resp.users)
                    }
                    if (resp.results && resp.results.length > 0) {
                        const result = resp.results[0]
                        path = result.path
                        actions.createSavedItem(result)
                    }
                }

                if (path) {
                    actions.expandProjectFolder(path)
                    if (treeItem) {
                        actions.scrollToView(treeItem)
                    }
                }
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        projectTreeRef: (newRef: ProjectTreeRef | null) => {
            if (newRef) {
                if (newRef.ref === null) {
                    if (typeof values.lastNewFolder === 'string') {
                        actions.assureVisibility({ type: 'folder', ref: values.lastNewFolder })
                    }
                } else {
                    actions.assureVisibility(newRef)
                }
            }
        },
    })),
    afterMount(({ actions, values, props }) => {
        if (props.root) {
            if (props.root.startsWith('project://')) {
                actions.loadFolder(props.root.slice('project://'.length))
            }
        } else {
            actions.loadFolder('')
        }
        if (values.projectTreeRef) {
            actions.assureVisibility(values.projectTreeRef)
        }
        if (typeof props.defaultOnlyFolders !== 'undefined') {
            actions.setOnlyFolders(props.defaultOnlyFolders)
        }
        if (typeof props.defaultSortMethod !== 'undefined') {
            actions.setSortMethod(props.defaultSortMethod)
        }
    }),
    propsChanged(({ actions, props, values }, oldProps) => {
        if (props.root !== oldProps.root) {
            const expandedFolders = values.expandedFolders.filter((f) => f !== oldProps.root)
            if (props.root) {
                expandedFolders.push(props.root)
            }
            actions.setExpandedFolders(expandedFolders)
            if (props.root) {
                actions.loadFolderIfNotLoaded(props.root)
            }
        }
    }),
])

export function refreshTreeItem(type: string, ref: string): void {
    projectTreeDataLogic.findMounted()?.actions.syncTypeAndRef(type, ref)
}

export function deleteFromTree(type: string, ref: string): void {
    projectTreeDataLogic.findMounted()?.actions.deleteTypeAndRef(type, ref)
}

export function getLastNewFolder(): string | undefined {
    return projectTreeLogic.findMounted({ key: PROJECT_TREE_KEY })?.values.lastNewFolder ?? undefined
}
