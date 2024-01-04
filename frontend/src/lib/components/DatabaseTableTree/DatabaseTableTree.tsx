import './Tree.scss'

import { DataWarehouseSceneRow } from 'scenes/data-warehouse/types'

import { TreeFolderRow, TreeRow } from './TreeRow'

export interface TreeProps {
    children?: React.ReactNode
    className?: string
    items: TreeItem[]
    depth?: number
    onSelectRow?: (row: DataWarehouseSceneRow) => void
}

export type TreeItem = TreeItemFolder | TreeItemLeaf

export interface TreeItemFolder {
    name: string
    items: TreeItemLeaf[]
}

export interface TreeItemLeaf {
    table: DataWarehouseSceneRow
    icon?: React.ReactNode
}

export function DatabaseTableTree({
    className = 'Tree__root rounded-lg',
    items,
    onSelectRow,
    depth = 1,
}: TreeProps): JSX.Element {
    return (
        <ul className={`Tree ${className}`}>
            {items.map((item, index) => {
                if ('items' in item) {
                    return <TreeFolderRow key={depth + '_' + index} item={item} depth={depth} onClick={onSelectRow} />
                }
                return <TreeRow key={depth + '_' + index} item={item} depth={depth} onClick={onSelectRow} />
            })}
        </ul>
    )
}
