import { IconPlus } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'

import { iconForType } from './defaultTree'
import { FolderState } from './types'

export function convertFileSystemEntryToTreeDataItem(
    imports: (FileSystemImport | FileSystemEntry)[],
    folderStates: Record<string, FolderState>,
    root = 'project'
): TreeDataItem[] {
    // The top-level nodes for our project tree
    const rootNodes: TreeDataItem[] = []

    // Helper to find an existing folder node or create one if it doesn't exist.
    const findOrCreateFolder = (nodes: TreeDataItem[], folderName: string, fullPath: string): TreeDataItem => {
        let folderNode: TreeDataItem | undefined = nodes.find((node) => node.record?.path === fullPath)
        if (!folderNode) {
            folderNode = {
                id: `${root}/${fullPath}`,
                name: folderName,
                record: { type: 'folder', id: `${root}/${fullPath}`, path: fullPath },
                children: [],
            }
            nodes.push(folderNode)
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

        if (item.type === 'folder' && currentLevel.find((node) => node.record?.path === item.path)) {
            continue
        }

        // Create the actual item node.
        const node: TreeDataItem = {
            id: `${root}/${item.id || item.path}`,
            name: itemName,
            icon: ('icon' in item && item.icon) || iconForType(item.type),
            record: item,
            onClick: () => {
                if (item.href) {
                    router.actions.push(typeof item.href === 'function' ? item.href(item.ref) : item.href)
                }
            },
        }
        // Place the item in the current (deepest) folder.
        currentLevel.push(node)

        if (item.type === 'folder') {
            if (!node.children) {
                node.children = []
            }
            if (folderStates[item.path] === 'has-more') {
                node.children.push({
                    id: `${root}-load-more/${item.path}`,
                    name: 'Load more...',
                    icon: <IconPlus />,
                })
            } else if (folderStates[item.path] === 'loading') {
                node.children.push({
                    id: `${root}-loading/${item.path}`,
                    name: 'Loading...',
                    icon: <Spinner />,
                })
            }
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
            return a.name.localeCompare(b.name)
        })
        for (const node of nodes) {
            if (node.children) {
                sortNodes(node.children)
            }
        }
    }
    sortNodes(rootNodes)
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

export function findInProjectTreeByPath(path: string, projectTree: TreeDataItem[]): TreeDataItem | undefined {
    for (const node of projectTree) {
        if (node.record?.path === path) {
            return node
        }
        if (node.children) {
            const found = findInProjectTreeByPath(path, node.children)
            if (found) {
                return found
            }
        }
    }
    return undefined
}
