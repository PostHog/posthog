import { LemonMenuItem } from '@posthog/lemon-ui'

import { DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { TreeFolderRow, TreeRow, TreeTableRow } from './TreeRow'

export interface TreeProps {
    className?: string
    items: TreeItem[]
    depth?: number
    onSelectRow?: (row: DatabaseSchemaTable) => void
    selectedRow?: DatabaseSchemaTable | null
}

export type TreeItem = TreeItemFolder | TreeItemLeaf | TreeTableItemLeaf

export interface TreeItemFolder {
    name: string
    table?: DatabaseSchemaTable
    dropdownOverlay?: React.ReactNode
    items: TreeItem[]
    emptyLabel?: JSX.Element
    isLoading?: boolean
}

export interface TreeTableItemLeaf {
    table: DatabaseSchemaTable
    icon?: React.ReactNode
}

export interface TreeItemLeaf {
    name: string
    type: string
    icon?: React.ReactNode
    menuItems?: LemonMenuItem[]
}

export function DatabaseTableTree({ items, onSelectRow, selectedRow, depth = 1, className }: TreeProps): JSX.Element {
    return (
        <ul className={className}>
            {items.map((item, index) => {
                if ('items' in item) {
                    return (
                        <TreeFolderRow
                            key={depth + '_' + index}
                            dropdownOverlay={item.dropdownOverlay}
                            item={item}
                            depth={depth}
                            onClick={onSelectRow}
                            selectedRow={selectedRow}
                        />
                    )
                }

                if ('table' in item) {
                    return (
                        <TreeTableRow
                            key={depth + '_' + index}
                            item={item}
                            depth={depth}
                            onClick={onSelectRow}
                            selected={!!(selectedRow?.name == item.table.name)}
                        />
                    )
                }

                return (
                    <TreeRow
                        key={depth + '_' + index}
                        item={item}
                        depth={depth}
                        onClick={onSelectRow}
                        selected={!!(selectedRow?.name == item.name)}
                        menuItems={item.menuItems}
                    />
                )
            })}
        </ul>
    )
}
