import './TreeRow.scss'

import { IconChevronDown } from '@posthog/icons'
import clsx from 'clsx'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { DataWarehouseSceneRow } from 'scenes/data-warehouse/types'

import { DatabaseTableTree, TreeItemFolder, TreeItemLeaf } from './DatabaseTableTree'

export interface TreeRowProps {
    item: TreeItemLeaf
    depth: number
    onClick?: (row: DataWarehouseSceneRow) => void
    selected?: boolean
}

export function TreeRow({ item, onClick, selected }: TreeRowProps): JSX.Element {
    const _onClick = (): void => {
        onClick && onClick(item.table)
    }

    return (
        <li>
            <div className={clsx('TreeRow', selected ? 'TreeRow__selected' : '')} onClick={_onClick}>
                <span className="mr-2">{item.icon}</span>
                {item.table.name}
            </div>
        </li>
    )
}

export interface TreeFolderRowProps {
    item: TreeItemFolder
    depth: number
    onClick?: (row: DataWarehouseSceneRow) => void
    emptyLabel?: JSX.Element
    selectedRow?: DataWarehouseSceneRow | null
}

export function TreeFolderRow({ item, depth, onClick, emptyLabel, selectedRow }: TreeFolderRowProps): JSX.Element {
    const [collapsed, setCollapsed] = useState(false)
    const { name, items } = item

    const _onClick = (): void => {
        setCollapsed(!collapsed)
    }

    return (
        <li>
            <div className={clsx('TreeRow', 'font-bold')} onClick={_onClick}>
                <span className="mr-2">{collapsed ? <IconChevronRight /> : <IconChevronDown />}</span>
                {name}
            </div>
            {!collapsed &&
                (items.length > 0 ? (
                    <DatabaseTableTree
                        className={`ml-${7 * depth}`}
                        items={items}
                        depth={depth * 2}
                        onSelectRow={onClick}
                        selectedRow={selectedRow}
                    />
                ) : emptyLabel ? (
                    emptyLabel
                ) : (
                    <div className={`ml-${7 * depth} text-muted`}>No tables found</div>
                ))}
        </li>
    )
}
