import { IconChevronDown, IconFolder } from '@posthog/icons'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

export const limitTableTreeCategories = (
    items: TreeDataItem[],
    shownFolderIds: string[],
    showAllTables: (folderId: string) => void
): TreeDataItem[] =>
    items.map((item) => {
        if (!item.children || item.record?.type === 'table') {
            return item
        }

        if (item.record?.type === 'source-folder' && item.children.length > 15 && !shownFolderIds.includes(item.id)) {
            return {
                ...item,
                children: [
                    ...item.children.slice(0, 15),
                    {
                        id: `${item.id}-show-all-tables`,
                        name: 'Show all',
                        displayName: <span className="text-link">Show all</span>,
                        icon: <IconChevronDown />,
                        record: { type: 'show-all-tables' },
                        onClick: () => showAllTables(item.id),
                    },
                ],
            }
        }

        return { ...item, children: limitTableTreeCategories(item.children, shownFolderIds, showAllTables) }
    })

const getDirectConnectionSchemaName = (tableNode: TreeDataItem, defaultSchemaName?: string | null): string | null => {
    const tableName =
        tableNode.record?.type === 'table' ? (tableNode.record.table?.name ?? tableNode.name) : tableNode.name
    const dotIndex = tableName.indexOf('.')

    if (dotIndex > 0) {
        return tableName.slice(0, dotIndex)
    }

    if (defaultSchemaName && defaultSchemaName.trim()) {
        return defaultSchemaName.trim()
    }

    return null
}

const getDirectConnectionDisplayTableName = (tableNode: TreeDataItem): string => {
    const tableName =
        tableNode.record?.type === 'table' ? (tableNode.record.table?.name ?? tableNode.name) : tableNode.name
    const dotIndex = tableName.indexOf('.')

    return dotIndex > 0 ? tableName.slice(dotIndex + 1) : tableName
}

export const groupDirectConnectionTableNodesBySchema = (
    tableNodes: TreeDataItem[],
    isSearch: boolean,
    defaultSchemaName?: string | null
): TreeDataItem[] => {
    const tablesBySchema = new Map<string, TreeDataItem[]>()
    const ungroupedTables: TreeDataItem[] = []

    tableNodes.forEach((tableNode) => {
        const schemaName = getDirectConnectionSchemaName(tableNode, defaultSchemaName)

        if (!schemaName) {
            ungroupedTables.push(tableNode)
            return
        }

        const currentNodes = tablesBySchema.get(schemaName) ?? []
        currentNodes.push({
            ...tableNode,
            displayName: getDirectConnectionDisplayTableName(tableNode),
        })
        tablesBySchema.set(schemaName, currentNodes)
    })

    const schemaFolders = Array.from(tablesBySchema.entries())
        .sort(([leftSchema], [rightSchema]) => leftSchema.localeCompare(rightSchema))
        .map(([schemaName, schemaTables]) => ({
            id: `${isSearch ? 'search-' : ''}schema-${schemaName}`,
            name: schemaName,
            type: 'node' as const,
            icon: <IconFolder />,
            record: {
                type: 'source-folder',
                sourceType: schemaName,
            },
            children: [...schemaTables].sort((leftTable, rightTable) => leftTable.name.localeCompare(rightTable.name)),
        }))

    if (ungroupedTables.length > 0) {
        schemaFolders.push({
            id: `${isSearch ? 'search-' : ''}schema-ungrouped`,
            name: defaultSchemaName?.trim() || 'Tables',
            type: 'node',
            icon: <IconFolder />,
            record: {
                type: 'source-folder',
                sourceType: defaultSchemaName?.trim() || 'Tables',
            },
            children: [...ungroupedTables].sort((leftTable, rightTable) =>
                leftTable.name.localeCompare(rightTable.name)
            ),
        })
    }

    return schemaFolders
}
