import { IconChevronDown } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'
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
            <LemonButton size="xsmall" fullWidth active={selected} icon={item.icon ? <>{item.icon}</> : null}>
                <span className="flex-1 flex justify-between">
                    <span className="truncate">{item.name}</span>
                    <span className="whitespace-nowrap">{item.type}</span>
                </span>
            </LemonButton>
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
            <LemonButton
                size="xsmall"
                fullWidth
                onClick={_onClick}
                active={selected}
                icon={item.icon ? <>{item.icon}</> : null}
            >
                <span className="truncate">{item.table.name}</span>
            </LemonButton>
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
            <LemonButton
                size="small"
                fullWidth
                onClick={_onClick}
                icon={<IconChevronDown className={collapsed ? 'rotate-270' : undefined} />}
            >
                {name}
            </LemonButton>
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
                            marginLeft: `${depth * 2}rem`,
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
