import './TreeRow.scss'

import { IconChevronDown } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { useCallback, useState } from 'react'

import { DatabaseSchemaTable } from '~/queries/schema'

import { DatabaseTableTree, TreeItemFolder, TreeItemLeaf, TreeTableItemLeaf } from './DatabaseTableTree'

export interface TreeRowProps {
    item: TreeItemLeaf
    depth: number
    onClick?: (row: DatabaseSchemaTable) => void
    selected?: boolean
}

export function TreeRow({ item, selected }: TreeRowProps): JSX.Element {
    return (
        <li>
            <div className={clsx('TreeRow text-ellipsis cursor-default', selected ? 'TreeRow__selected' : '')}>
                <span className="mr-2">{item.icon}</span>
                <div className="flex flex-row justify-between w-100">
                    <div className="w-40 overflow-hidden text-ellipsis whitespace-nowrap">{item.name}</div>
                    <div className="text-right whitespace-nowrap">{item.type}</div>
                </div>
            </div>
        </li>
    )
}

export interface TreeTableRowProps {
    item: TreeTableItemLeaf
    depth: number
    onClick?: (row: DatabaseSchemaTable) => void
    selected?: boolean
}

export function TreeTableRow({ item, onClick, selected }: TreeTableRowProps): JSX.Element {
    const _onClick = useCallback(() => {
        onClick && onClick(item.table)
    }, [onClick, item])

    return (
        <li>
            <div className={clsx('TreeRow text-ellipsis', selected ? 'TreeRow__selected' : '')} onClick={_onClick}>
                <span className="mr-2">{item.icon}</span>
                <div className="overflow-hidden text-ellipsis whitespace-nowrap">{item.table.name}</div>
            </div>
        </li>
    )
}

export interface TreeFolderRowProps {
    item: TreeItemFolder
    depth: number
    onClick?: (row: DatabaseSchemaTable) => void
    selectedRow?: DatabaseSchemaTable | null
}

export function TreeFolderRow({ item, depth, onClick, selectedRow }: TreeFolderRowProps): JSX.Element {
    const { name, items, emptyLabel } = item

    const isColumnType = items.length > 0 && 'type' in items[0]

    const [collapsed, setCollapsed] = useState(isColumnType)

    const _onClick = useCallback(() => {
        setCollapsed(!collapsed)
    }, [collapsed])

    return (
        <li className="overflow-hidden">
            <div className={clsx('TreeRow', isColumnType ? '' : 'font-bold')} onClick={_onClick}>
                <span className="mr-2">{collapsed ? <IconChevronRight /> : <IconChevronDown />}</span>
                {name}
            </div>
            {!collapsed &&
                (items.length > 0 ? (
                    <DatabaseTableTree
                        items={items}
                        depth={depth + 1}
                        onSelectRow={onClick}
                        selectedRow={selectedRow}
                        style={{ marginLeft: `14px`, padding: 0 }}
                    />
                ) : (
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            marginLeft: `${14 * depth}px`,
                        }}
                    >
                        {item.isLoading ? (
                            <Spinner className="mt-2" />
                        ) : emptyLabel ? (
                            emptyLabel
                        ) : (
                            <span className="text-muted">No tables found</span>
                        )}
                    </div>
                ))}
        </li>
    )
}
