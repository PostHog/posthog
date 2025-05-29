import { IconArrowUpRight, IconPlus } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
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
}

export function wrapWithShortutIcon(item: FileSystemImport | FileSystemEntry, icon: JSX.Element): JSX.Element {
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
}: ConvertProps): TreeDataItem[] {
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
        const itemName = pathSplit.pop()!
        const folderPath = joinPath(pathSplit)

        // Split the folder path by "/" (ignoring empty parts).
        const folderParts = folderPath ? splitPath(folderPath) : []

        // Start at the root level.
        let currentLevel = rootNodes
        let folderNode: TreeDataItem | undefined = undefined
        const accumulatedPath: string[] = []

        // Create (or find) nested folders as needed.
        for (const part of folderParts) {
            accumulatedPath.push(part)
            folderNode = findOrCreateFolder(currentLevel, part, joinPath(accumulatedPath))
            currentLevel = folderNode.children!
        }

        let accumulatedChildren: TreeDataItem[] = []
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
                    if (existingFolder.children) {
                        accumulatedChildren = [...accumulatedChildren, ...existingFolder.children]
                    }
                }
            }
        }

        // Create the actual item node.
        const nodeId = item.type === 'folder' ? `${root}-folder/${item.path}` : `${root}/${item.id || item.path}`
        const node: TreeDataItem = {
            id: nodeId,
            name: itemName,
            displayName: <SearchHighlightMultiple string={itemName} substring={searchTerm ?? ''} />,
            icon: item._loading ? (
                <Spinner />
            ) : (
                wrapWithShortutIcon(item, ('icon' in item && item.icon) || iconForType(item.type))
            ),
            record: item,
            checked: checkedItems[nodeId],
            onClick: () => {
                if (item.href) {
                    router.actions.push(typeof item.href === 'function' ? item.href(item.ref) : item.href)
                }
            },
        }
        if (disableFolderSelect) {
            if (item.type === 'folder') {
                node.disableSelect = true
            }
        } else if (checkedItems[nodeId]) {
            markIndeterminateFolders(joinPath(splitPath(item.path).slice(0, -1)))
        }

        // Place the item in the current (deepest) folder.
        currentLevel.push(node)

        if (item.type === 'folder') {
            if (!node.children) {
                node.children = []
            }
            if (accumulatedChildren) {
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
            return String(a.name).localeCompare(String(b.name))
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
