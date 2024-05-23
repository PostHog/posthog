import clsx from 'clsx'

import { DatabaseSchemaTable } from '~/queries/schema'

import { TreeFolderRow, TreeRow, TreeTableRow } from './TreeRow'

export interface TreeProps extends React.HTMLAttributes<HTMLUListElement> {
    children?: React.ReactNode
    className?: string
    items: TreeItem[]
    depth?: number
    onSelectRow?: (row: DatabaseSchemaTable) => void
    selectedRow?: DatabaseSchemaTable | null
}

export type TreeItem = TreeItemFolder | TreeItemLeaf | TreeTableItemLeaf

export interface TreeItemFolder {
    name: string
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
        <ul
            className={clsx(
                `bg-bg-light space-y-px rounded`,
                depth == 1 ? 'border p-2 overflow-y-auto flex-1' : '',
                className
            )}
            {...props}
        >
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
                    />
                )
            })}
        </ul>
    )
}
