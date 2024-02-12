import { DataWarehouseTableType } from 'scenes/data-warehouse/types'

import { TreeFolderRow, TreeRow } from './TreeRow'

export interface TreeProps extends React.HTMLAttributes<HTMLUListElement> {
    children?: React.ReactNode
    className?: string
    items: TreeItem[]
    depth?: number
    onSelectRow?: (row: DataWarehouseTableType) => void
    selectedRow?: DataWarehouseTableType | null
}

export type TreeItem = TreeItemFolder | TreeItemLeaf

export interface TreeItemFolder {
    name: string
    items: TreeItemLeaf[]
    emptyLabel?: JSX.Element
}

export interface TreeItemLeaf {
    table: DataWarehouseTableType
    icon?: React.ReactNode
}

export function DatabaseTableTree({
    className = '',
    items,
    onSelectRow,
    selectedRow,
    depth = 1,
    ...props
}: TreeProps): JSX.Element {
    return (
        <ul className={`bg-bg-light p-4 rounded-lg ${className}`} {...props}>
            {items.map((item, index) => {
                if ('items' in item) {
                    return (
                        <TreeFolderRow
                            key={depth + '_' + index}
                            item={item}
                            depth={depth}
                            onClick={onSelectRow}
                            selectedRow={selectedRow}
                        />
                    )
                }
                return (
                    <TreeRow
                        key={depth + '_' + index}
                        item={item}
                        depth={depth}
                        onClick={onSelectRow}
                        selected={!!(selectedRow?.name == item.table.name)}
                    />
                )
            })}
        </ul>
    )
}
