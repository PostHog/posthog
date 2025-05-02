import { IconArrowUpRight, IconPlus } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { RecentResults, SearchResults } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'

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
}

export function getItemId(item: FileSystemImport | FileSystemEntry, root: string = 'project'): string {
    return item.type === 'folder' ? `${root}-folder/${item.path}` : `${root}/${item.id || item.path}`
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

export function wrapWithShortcutIcon(item: FileSystemImport | FileSystemEntry, icon: JSX.Element): JSX.Element {
    if (item.shortcut) {
        return (
            <div className="relative">
                {icon}
                <IconArrowUpRight className="absolute bottom-[-0.25rem] left-[-0.25rem] scale-75 bg-white border border-black" />
            </div>
        )
    }

    return icon
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
}: ConvertProps): TreeDataItem[] {
    function itemToTreeDataItem(item: FileSystemImport | FileSystemEntry): TreeDataItem {
        const pathSplit = splitPath(item.path)
        const itemName = pathSplit.pop()!
        const nodeId = getItemId(item)
        const displayName = <SearchHighlightMultiple string={itemName} substring={searchTerm ?? ''} />
        const node: TreeDataItem = {
            id: nodeId,
            name: itemName,
            displayName: recent ? (
                <>
                    {displayName}{' '}
                    <span className="text-muted text-xs font-normal">- {dayjs(item.created_at).fromNow()}</span>
                </>
            ) : (
                <>{displayName}</>
            ),
            icon: item._loading ? (
                <Spinner />
            ) : (
                wrapWithShortcutIcon(item, ('icon' in item && item.icon) || iconForType(item.type))
            ),
            record: item,
            checked: checkedItems[nodeId],
            onClick: () => {
                if (item.href) {
                    router.actions.push(typeof item.href === 'function' ? item.href(item.ref) : item.href)
                }
            },
        }
        if (item && disabledReason?.(item)) {
            node.disabledReason = disabledReason(item)
            node.onClick = undefined
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
            indeterminateFolders[`${root}-folder/${joinPath(parts.slice(0, i + 1))}`] = true
        }
    }

    // Helper to find an existing folder node or create one if it doesn't exist.
    const findOrCreateFolder = (nodes: TreeDataItem[], folderName: string, fullPath: string): TreeDataItem => {
        let folderNode: TreeDataItem | undefined = nodes.find(
            (node) => node.record?.path === fullPath && node.record?.type === 'folder'
        )
        if (!folderNode) {
            const id = `${root}-folder/${fullPath}`
            folderNode = {
                id,
                name: folderName,
                displayName: <SearchHighlightMultiple string={folderName} substring={searchTerm ?? ''} />,
                record: { type: 'folder', id: null, path: fullPath },
                children: [],
                checked: checkedItems[id],
            }
            if (disableFolderSelect) {
                folderNode.disableSelect = true
            }
            if (folderNode.record && disabledReason?.(folderNode.record as FileSystemEntry)) {
                folderNode.disabledReason = disabledReason(folderNode.record as FileSystemEntry)
                folderNode.onClick = undefined
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
                    icon: <IconPlus />,
                    disableSelect: true,
                })
            } else if (folderStates[item.path] === 'loading') {
                node.children.push({
                    id: `${root}-loading/${item.path}`,
                    name: 'Loading...',
                    icon: <Spinner />,
                    disableSelect: true,
                })
            }
            allFolderNodes.push(node)
        }
    }

    // Helper function to sort nodes (and their children) alphabetically by name.
    const sortNodes = (nodes: TreeDataItem[]): void => {
        nodes.sort((a, b) => {
            if (a.id.startsWith(`${root}-load-more/`) || a.id.startsWith(`${root}-loading/`)) {
                return 1
            }
            if (b.id.startsWith(`${root}-load-more/`) || b.id.startsWith(`${root}-loading/`)) {
                return -1
            }
            // folders before files
            if (a.record?.type === 'folder' && b.record?.type !== 'folder') {
                return -1
            }
            if (b.record?.type === 'folder' && a.record?.type !== 'folder') {
                return 1
            }
            return String(a.name).localeCompare(String(b.name), undefined, { sensitivity: 'accent' })
        })
        for (const node of nodes) {
            if (node.children) {
                sortNodes(node.children)
            }
        }
    }
    sortNodes(rootNodes)
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
export function splitPath(path: string): string[] {
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
