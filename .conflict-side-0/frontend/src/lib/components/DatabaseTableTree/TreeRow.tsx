import clsx from 'clsx'
import { useCallback, useState } from 'react'

import { IconChevronDown, IconClock, IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItem, Spinner, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { DatabaseTableTree, TreeItemFolder, TreeItemLeaf, TreeTableItemLeaf } from './DatabaseTableTree'

export interface TreeRowProps {
    item: TreeItemLeaf
    depth: number
    onClick?: (row: DatabaseSchemaTable) => void
    selected?: boolean
    menuItems?: LemonMenuItem[]
}

export function TreeRow({ item, menuItems }: TreeRowProps): JSX.Element {
    const [isMenuOpen, setIsMenuOpen] = useState(false)

    return (
        <li className={clsx('relative flex items-center', isMenuOpen && 'bg-surface-primary')}>
            <LemonButton
                onClick={() => {
                    void copyToClipboard(item.name, item.name)
                }}
                size="xsmall"
                fullWidth
                icon={item.icon ? <>{item.icon}</> : null}
                className="font-mono"
            >
                <span className="flex-1 flex gap-2">
                    <span className="truncate">{item.name}</span>
                    <span className="italic text-secondary">{item.type}</span>
                </span>
            </LemonButton>
            {menuItems && menuItems.length > 0 && (
                <LemonMenu items={menuItems} onVisibilityChange={setIsMenuOpen}>
                    <div className="absolute right-1 flex">
                        <LemonButton size="small" noPadding icon={<IconEllipsis />} />
                    </div>
                </LemonMenu>
            )}
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
                className="font-mono"
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
    dropdownOverlay?: React.ReactNode
}

export function TreeFolderRow({ item, depth, onClick, selectedRow, dropdownOverlay }: TreeFolderRowProps): JSX.Element {
    const { name, items, emptyLabel } = item

    const isColumnType = items.length > 0 && 'type' in items[0]

    const [collapsed, setCollapsed] = useState(isColumnType)

    const _onClick = useCallback(() => {
        setCollapsed(!collapsed)
    }, [collapsed])

    const getTooltipLabel = (): string => {
        if (item.table?.type === 'materialized_view') {
            if (item.table.status === 'Running') {
                return `Materialization running`
            }
            if (item.table.status === 'Failed') {
                return `Materialization failed`
            }
            if (item.table.status === 'Modified') {
                return `View definition modified since last materialization`
            }
            if (item.table.status === 'Completed') {
                return `Last materialized ${humanFriendlyDetailedTime(item.table.last_run_at)}`
            }
        }
        return ''
    }

    const getIconColor = (): 'text-accent' | 'text-danger' | 'text-warning' | 'text-success' => {
        if (item.table?.type === 'materialized_view') {
            if (item.table.status === 'Running') {
                return 'text-accent'
            }
            if (item.table.status === 'Failed') {
                return 'text-danger'
            }
            if (item.table.status === 'Modified') {
                return 'text-warning'
            }
        }
        return 'text-success'
    }

    return (
        <li className="overflow-hidden">
            <LemonButton
                size="small"
                className="font-mono"
                fullWidth
                onClick={_onClick}
                sideAction={
                    dropdownOverlay
                        ? {
                              icon: <IconEllipsis fontSize={12} />,

                              dropdown: {
                                  overlay: dropdownOverlay,
                              },
                          }
                        : undefined
                }
                icon={<IconChevronDown className={collapsed ? 'rotate-270' : undefined} />}
                tooltip={name}
            >
                <div className="flex flex-row w-full justify-between">
                    <span className="truncate">{name}</span>
                    {item.table?.type === 'materialized_view' && (
                        <Tooltip title={getTooltipLabel()}>
                            <IconClock className={clsx(getIconColor())} />
                        </Tooltip>
                    )}
                </div>
            </LemonButton>
            {!collapsed &&
                (items.length > 0 && !item.isLoading ? (
                    <DatabaseTableTree
                        items={items}
                        depth={depth + 1}
                        onSelectRow={onClick}
                        selectedRow={selectedRow}
                        className="ml-4"
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
                            <span className="text-secondary">No tables found</span>
                        )}
                    </div>
                ))}
        </li>
    )
}
