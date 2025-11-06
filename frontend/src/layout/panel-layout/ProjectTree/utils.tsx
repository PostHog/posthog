import { IconPlus, IconShortcut } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { RecentResults, SearchResults } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { FileSystemEntry, FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'
import { UserBasicType } from '~/types'

import { iconForType } from './defaultTree'
import { FolderState } from './types'

export interface ConvertProps {
    imports: (FileSystemImport | FileSystemEntry)[]
    folderStates: Record<string, FolderState>
    checkedItems: Record<string, boolean>
    root: string
    searchTerm?: string
    disableFolderSelect?: boolean
    disabledReason?: (item: FileSystemImport | FileSystemEntry) => string | undefined
    recent?: boolean
    users?: Record<string, UserBasicType>
    foldersFirst?: boolean
    allShortcuts?: boolean
}

export function getItemId(item: FileSystemImport | FileSystemEntry, protocol = 'project://'): string {
    const root = protocol.replace(/\/+/, '').replace(':', '')
    return item.type === 'folder' ? `${root}://${item.path}` : `${root}/${item.id || item.path}`
}

export function protocolTitle(str: string): string {
    return (str.charAt(0).toUpperCase() + str.slice(1)).replaceAll('-', ' ')
}

export function splitProtocolPath(url: string): [string, string] {
    const folders = url ? splitPath(url) : []
    const urlWithProtocol = folders.length > 0 && folders[0].endsWith(':') && url.startsWith(`${folders[0]}//`)
    if (urlWithProtocol) {
        return [folders[0] + '//', joinPath(folders.slice(1))]
    }
    return ['products://', url]
}

export function formatUrlAsName(url: string, defaultName = 'Pinned'): string {
    const parts = splitPath(url)
    if (parts[0]?.endsWith(':') && url.startsWith(`${parts[0]}//`)) {
        if (parts.length > 1) {
            return parts[parts.length - 1]
        }
        return protocolTitle(parts[0].slice(0, -1))
    }
    if (parts.length > 0) {
        return parts[parts.length - 1]
    }
    return defaultName
}

export function sortFilesAndFolders(a: FileSystemEntry, b: FileSystemEntry): number {
    const parentA = a.path.substring(0, a.path.lastIndexOf('/'))
    const parentB = b.path.substring(0, b.path.lastIndexOf('/'))

    if (parentA === parentB) {
        if (a.type === 'folder' && b.type !== 'folder') {
            return -1
        }
        if (b.type === 'folder' && a.type !== 'folder') {
            return 1
        }
    }
    return a.path.localeCompare(b.path, undefined, { sensitivity: 'accent' })
}

export function wrapWithShortcutIcon(icon: React.ReactNode): JSX.Element {
    return (
        <div className="relative">
            {icon}
            <IconShortcut className="icon-shortcut absolute bottom-[-0.15rem] left-[-0.25rem] [&_path]:fill-white" />
        </div>
    )
}

export function convertFileSystemEntryToTreeDataItem({
    imports,
    folderStates,
    checkedItems,
    root,
    searchTerm,
    disableFolderSelect,
    disabledReason,
    recent,
    users,
    foldersFirst = true,
    allShortcuts = false,
}: ConvertProps): TreeDataItem[] {
    function itemToTreeDataItem(item: FileSystemImport | FileSystemEntry): TreeDataItem {
        const pathSplit = splitPath(item.path)
        const itemName = unescapePath(pathSplit.pop() ?? 'Unnamed')
        const nodeId = getItemId(item, root)
        const displayName = <SearchHighlightMultiple string={itemName} substring={searchTerm ?? ''} />
        const user: UserBasicType | undefined = item.meta?.created_by ? users?.[item.meta.created_by] : undefined

        const icon = iconForType(('iconType' in item ? item.iconType : undefined) || (item.type as FileSystemIconType))
        const node: TreeDataItem = {
            id: nodeId,
            name: itemName,
            displayName,
            icon: item._loading ? <Spinner /> : item.shortcut || allShortcuts ? wrapWithShortcutIcon(icon) : icon,
            record: { ...item, user },
            checked: checkedItems[nodeId],
            tags: item.tags,
            visualOrder: item.visualOrder,
        }
        if (item && disabledReason?.(item)) {
            node.disabledReason = disabledReason(item)
        }
        if (disableFolderSelect && item.type === 'folder') {
            node.disableSelect = true
        }
        return node
    }

    if (recent) {
        return imports.map(itemToTreeDataItem)
    }

    // The top-level nodes for our project tree
    const rootNodes: TreeDataItem[] = []

    // All folder nodes. Used later to add mock "empty folder" items.
    const allFolderNodes: TreeDataItem[] = []

    // Retroactively mark these as checked later on
    const indeterminateFolders: Record<string, boolean> = {}
    const markIndeterminateFolders = (path: string): void => {
        const parts = splitPath(path)
        for (let i = 0; i < parts.length; i++) {
            indeterminateFolders[`${root}${joinPath(parts.slice(0, i + 1))}`] = true
        }
    }

    // Helper to find an existing folder node or create one if it doesn't exist.
    const findOrCreateFolder = (nodes: TreeDataItem[], folderName: string, fullPath: string): TreeDataItem => {
        let folderNode: TreeDataItem | undefined = nodes.find(
            (node) => node.record?.path === fullPath && node.record?.type === 'folder'
        )
        if (!folderNode) {
            const id = `${root}${fullPath}`
            const [protocol] = splitProtocolPath(id)
            folderNode = {
                id,
                name: folderName,
                displayName: <SearchHighlightMultiple string={folderName} substring={searchTerm ?? ''} />,
                record: { type: 'folder', id: null, protocol, path: fullPath },
                children: [],
                checked: checkedItems[id],
            }
            if (disableFolderSelect) {
                folderNode.disableSelect = true
            }
            if (folderNode.record && disabledReason?.(folderNode.record as FileSystemEntry)) {
                folderNode.disabledReason = disabledReason(folderNode.record as FileSystemEntry)
            }
            allFolderNodes.push(folderNode)
            nodes.push(folderNode)
            if (checkedItems[id]) {
                markIndeterminateFolders(fullPath)
            }
        }
        if (!folderNode.children) {
            folderNode.children = []
        }
        return folderNode
    }

    // Iterate over each raw project item.
    for (const item of imports) {
        const pathSplit = splitPath(item.path)
        pathSplit.pop()
        const folderPath = joinPath(pathSplit)

        // Start at the root level.
        let currentLevel = rootNodes
        let folderNode: TreeDataItem | undefined = undefined
        const accumulatedPath: string[] = []
        let accumulatedChildren: TreeDataItem[] = []

        const folderParts = folderPath ? splitPath(folderPath) : []

        // Create (or find) nested folders as needed.
        for (const part of folderParts) {
            accumulatedPath.push(part)
            folderNode = findOrCreateFolder(currentLevel, part, joinPath(accumulatedPath))
            currentLevel = folderNode.children!
        }

        if (item.type === 'folder') {
            const folderMatch = (node: TreeDataItem): boolean =>
                node.record?.path === item.path && node.record?.type === 'folder'
            const existingFolder = currentLevel.find(folderMatch)
            if (existingFolder) {
                if (existingFolder.record?.id) {
                    continue
                } else {
                    // We have a folder without an id, but the incoming one has an id. Remove the current one
                    currentLevel = currentLevel.filter((node) => !folderMatch(node))
                    if (folderNode) {
                        folderNode.children = currentLevel
                    }
                    if (existingFolder.children) {
                        accumulatedChildren = [...accumulatedChildren, ...existingFolder.children]
                    }
                }
            }
        }

        const nodeId = getItemId(item)
        const node = itemToTreeDataItem(item)

        if (checkedItems[nodeId]) {
            markIndeterminateFolders(joinPath(splitPath(item.path).slice(0, -1)))
        }

        // Place the item in the current (deepest) folder.
        currentLevel.push(node)

        if (item.type === 'folder') {
            if (!node.children) {
                node.children = []
            }
            if (accumulatedChildren && accumulatedChildren.length > 0) {
                node.children = [...node.children, ...accumulatedChildren]
            }
            if (folderStates[item.path] === 'has-more') {
                node.children.push({
                    id: `${root}-load-more/${item.path}`,
                    name: 'Load more...',
                    displayName: <>Load more...</>,
                    icon: <IconPlus />,
                    disableSelect: true,
                })
            } else if (folderStates[item.path] === 'loading') {
                node.children.push({
                    id: `${root}-loading/${item.path}`,
                    name: 'Loading...',
                    displayName: <>Loading...</>,
                    icon: <Spinner />,
                    disableSelect: true,
                    type: 'loading-indicator',
                })
            }
            allFolderNodes.push(node)
        }
    }

    // Helper function to sort nodes (and their children) alphabetically by name.
    const sortNodes = (nodes: TreeDataItem[]): void => {
        nodes.sort((a, b) => {
            // If they have a category, sort by that
            if (a.record?.category && b.record?.category && a.record.category !== b.record.category) {
                return a.record.category.localeCompare(b.record.category, undefined, { sensitivity: 'accent' })
            }

            // Sort by visualOrder if both items have it
            if (a.visualOrder !== undefined && b.visualOrder !== undefined) {
                return a.visualOrder - b.visualOrder
            }
            // If only one has visualOrder, prioritize it
            if (a.visualOrder !== undefined) {
                return -1
            }
            if (b.visualOrder !== undefined) {
                return 1
            }

            if (a.id.startsWith(`${root}-load-more/`) || a.id.startsWith(`${root}-loading/`)) {
                return 1
            }
            if (b.id.startsWith(`${root}-load-more/`) || b.id.startsWith(`${root}-loading/`)) {
                return -1
            }
            if (foldersFirst) {
                if (a.record?.type === 'folder' && b.record?.type !== 'folder') {
                    return -1
                }
                if (b.record?.type === 'folder' && a.record?.type !== 'folder') {
                    return 1
                }
            }
            return String(a.name).localeCompare(String(b.name), undefined, { sensitivity: 'accent' })
        })
        for (const node of nodes) {
            if (node.children) {
                sortNodes(node.children)
            }
        }
    }

    if (root !== 'persons://') {
        sortNodes(rootNodes)
    }

    for (const folderNode of allFolderNodes) {
        if (folderNode.children && folderNode.children.length === 0) {
            folderNode.children.push({
                id: `${root}-folder-empty/${folderNode.id}`,
                name: 'Empty folder',
                displayName: <>Empty folder</>,
                disableSelect: true,
                type: 'empty-folder',
            })
        }
        if (indeterminateFolders[folderNode.id] && !folderNode.checked) {
            folderNode.checked = 'indeterminate'
        }
    }

    if (rootNodes.find((node) => node.record?.category)) {
        const newRootNodes: TreeDataItem[] = []
        let lastCategory: string | null = null
        for (const node of rootNodes) {
            if (node.record?.category && node.record.category !== lastCategory) {
                newRootNodes.push({
                    id: `${node.id}-category`,
                    name: node.record.category,
                    displayName: <>{node.record.category}</>,
                    type: 'category',
                })
                lastCategory = node.record.category
            }
            newRootNodes.push(node)
        }
        return newRootNodes
    }

    return rootNodes
}

/**
 * Splits `path` by unescaped "/" delimiters.
 *   - splitPath("a/b")            => ["a", "b"]
 *   - splitPath("a\\/b/c")        => ["a/b", "c"]
 *   - splitPath("a\\/b\\\\/c")    => ["a/b\\", "c"]
 *   - splitPath("a\n\t/b")        => ["a\n\t", "b"]
 *   - splitPath("a")              => ["a"]
 *   - splitPath("")               => []
 */
export function splitPath(path: string | undefined): string[] {
    if (!path) {
        return []
    }
    const segments: string[] = []
    let current = ''
    for (let i = 0; i < path.length; i++) {
        if (path[i] === '\\' && i < path.length - 1 && (path[i + 1] === '/' || path[i + 1] === '\\')) {
            current += path[i + 1]
            i++
            continue
        } else if (path[i] === '/') {
            segments.push(current)
            current = ''
        } else {
            current += path[i]
        }
    }
    segments.push(current)
    return segments.filter((s) => s !== '')
}

export function joinPath(path: string[]): string {
    return path.map(escapePath).join('/')
}

export function escapePath(path: string): string {
    return path.replace(/\\/g, '\\\\').replace(/\//g, '\\/')
}

export function unescapePath(path: string): string {
    return path.replace(/\\\//g, '/').replace(/\\\\/g, '\\')
}

export function findInProjectTree(itemId: string, projectTree: TreeDataItem[]): TreeDataItem | undefined {
    for (const node of projectTree) {
        if (node.id === itemId) {
            return node
        }
        if (node.children) {
            const found = findInProjectTree(itemId, node.children)
            if (found) {
                return found
            }
        }
    }
    return undefined
}

/**
 * Calculates the new path for a file system entry when moving it to a new destination folder
 * @param item The file system entry to move
 * @param destinationFolder The destination folder path (empty string for root)
 * @returns Object containing the new path and whether the move is valid
 */
export function calculateMovePath(
    item: FileSystemEntry,
    destinationFolder: string
): { newPath: string; isValidMove: boolean } {
    const oldPath = item.path
    const oldSplit = splitPath(oldPath)
    const fileName = oldSplit.pop()

    if (!fileName) {
        return { newPath: '', isValidMove: false }
    }

    let newPath = ''

    if (destinationFolder === '') {
        // Moving to root
        newPath = joinPath([fileName])
        // Only valid if item is not already at root
        const isValidMove = oldSplit.length > 0
        return { newPath, isValidMove }
    }
    // Moving to another folder
    newPath = joinPath([...splitPath(destinationFolder), fileName])
    // Only valid if destination is different from current location
    const isValidMove = newPath !== oldPath
    return { newPath, isValidMove }
}

export function appendResultsToFolders(
    results: RecentResults | SearchResults,
    folders: Record<string, FileSystemEntry[]>
): Record<string, FileSystemEntry[]> {
    // Append search results into the loaded state to persist data and help with multi-selection between panels
    const newState: Record<string, FileSystemEntry[]> = { ...folders }
    const newResults = 'lastCount' in results ? results.results.slice(-1 * results.lastCount) : results.results
    for (const result of newResults) {
        const folder = joinPath(splitPath(result.path).slice(0, -1))
        if (newState[folder]) {
            const existingItem = newState[folder].find((item) => item.id === result.id)
            if (existingItem) {
                newState[folder] = newState[folder].map((file) => (file.id === result.id ? result : file))
            } else {
                newState[folder] = [...newState[folder], result]
            }
        } else {
            newState[folder] = [result]
        }
    }
    return newState
}

export const isGroupViewShortcut = (shortcut: FileSystemEntry): boolean => {
    return !!shortcut?.type?.startsWith('group_') && !!shortcut?.type?.endsWith('_view')
}
