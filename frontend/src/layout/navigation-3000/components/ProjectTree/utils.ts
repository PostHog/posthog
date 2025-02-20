import { router } from 'kea-router'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { iconForType } from './defaultTree'
import { FileSystemImport } from './types'

export function convertFileSystemEntryToTreeDataItem(imports: FileSystemImport[]): TreeDataItem[] {
    // The top-level nodes for our project tree
    const rootNodes: TreeDataItem[] = []

    // Helper to find an existing folder node or create one if it doesn't exist.
    const findOrCreateFolder = (nodes: TreeDataItem[], folderName: string, fullPath: string): TreeDataItem => {
        let folderNode: TreeDataItem | undefined = nodes.find((node) => node.filePath === fullPath)
        if (!folderNode) {
            folderNode = {
                id: 'project/' + fullPath,
                name: folderName,
                record: { type: 'folder', id: 'project/' + fullPath, path: fullPath },
                children: [],
                type: 'folder' as const,
                filePath: fullPath,
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
        const pathSplit = item.path.split('/').filter(Boolean)
        const itemName = pathSplit.pop()!
        const folderPath = pathSplit.join('/')

        // Split the folder path by "/" (ignoring empty parts).
        const folderParts = folderPath ? folderPath.split('/').filter(Boolean) : []

        // Start at the root level.
        let currentLevel = rootNodes
        let accumulatedPath = ''

        // Create (or find) nested folders as needed.
        for (const part of folderParts) {
            accumulatedPath = accumulatedPath ? accumulatedPath + '/' + part : part
            const folderNode = findOrCreateFolder(currentLevel, part, accumulatedPath)
            currentLevel = folderNode.children!
        }

        if (item.type === 'folder' && currentLevel.find((node) => node.filePath === item.path)) {
            continue
        }

        // Create the actual item node.
        const node: TreeDataItem = {
            id: 'project/' + (item.id || item.path),
            name: itemName,
            icon: item.icon || iconForType(item.type),
            record: item,
            onClick: () => {
                if (item.href) {
                    router.actions.push(item.href)
                }
            },
            type: item.type === 'folder' ? ('folder' as const) : ('file' as const),
            filePath: item.path,
        }
        // Place the item in the current (deepest) folder.
        currentLevel.push(node)
    }

    // Helper function to sort nodes (and their children) alphabetically by name.
    const sortNodes = (nodes: TreeDataItem[]): void => {
        nodes.sort((a, b) => a.name.localeCompare(b.name))
        for (const node of nodes) {
            if (node.children) {
                sortNodes(node.children)
            }
        }
    }
    sortNodes(rootNodes)
    return rootNodes
}
