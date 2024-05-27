import { IconBrackets, IconChevronDown, IconDatabase } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { clsx } from 'clsx'
import { useActions, useValues } from 'kea'
import { DatabaseTableTree, TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useState } from 'react'
import { urls } from 'scenes/urls'

import { ViewLinkModal } from '../ViewLinkModal'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { TableData } from './TableData'

export const DataWarehouseTables = (): JSX.Element => {
    return (
        <>
            <div className="flex flex-wrap items-start gap-2 overflow-hidden">
                <DatabaseTableTreeWithItems />
                <div className="flex-3 min-w-80 overflow-hidden">
                    <TableData />
                </div>
            </div>
            <ViewLinkModal />
        </>
    )
}

interface DatabaseTableTreeProps {
    inline?: boolean
}

export const DatabaseTableTreeWithItems = ({ inline }: DatabaseTableTreeProps): JSX.Element => {
    const { dataWarehouseTablesBySourceType, posthogTables, databaseLoading, views, selectedRow } =
        useValues(dataWarehouseSceneLogic)
    const { selectRow } = useActions(dataWarehouseSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [collapsed, setCollapsed] = useState(false)

    const treeItems = (): TreeItem[] => {
        if (inline) {
            const items: TreeItem[] = [
                {
                    name: 'External',
                    items: Object.keys(dataWarehouseTablesBySourceType).map((source_type) => ({
                        name: source_type,
                        items: dataWarehouseTablesBySourceType[source_type].map((table) => ({
                            name: table.name,
                            items: Object.values(table.fields).map((column) => ({
                                name: column.name,
                                type: column.type,
                                icon: <IconDatabase />,
                            })),
                        })),
                    })),
                    emptyLabel: (
                        <span className="text-muted">
                            No tables found. <Link to={urls.dataWarehouseTable()}>Link source</Link>
                        </span>
                    ),
                    isLoading: databaseLoading,
                },
                {
                    name: 'PostHog',
                    items: posthogTables.map((table) => ({
                        name: table.name,
                        items: Object.values(table.fields).map((column) => ({
                            name: column.name,
                            type: column.type,
                            icon: <IconDatabase />,
                        })),
                    })),
                    isLoading: databaseLoading,
                },
            ]

            if (featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE]) {
                items.push({
                    name: 'Views',
                    items: views.map((table) => ({
                        name: table.name,
                        items: Object.values(table).map((column) => ({
                            name: column.name,
                            type: column.type,
                            icon: <IconDatabase />,
                        })),
                    })),
                    emptyLabel: <span className="text-muted">No views found</span>,
                    isLoading: databaseLoading,
                })
            }

            return items
        }

        const items: TreeItem[] = [
            {
                name: 'External',
                items: Object.keys(dataWarehouseTablesBySourceType).map((source_type) => ({
                    name: source_type,
                    items: dataWarehouseTablesBySourceType[source_type].map((table) => ({
                        table: table,
                        icon: <IconDatabase />,
                    })),
                })),
                emptyLabel: (
                    <span className="text-muted">
                        No tables found. <Link to={urls.dataWarehouseTable()}>Link source</Link>
                    </span>
                ),
                isLoading: databaseLoading,
            },
            {
                name: 'PostHog',
                items: posthogTables.map((table) => ({
                    table: table,
                    icon: <IconDatabase />,
                })),
                isLoading: databaseLoading,
            },
        ]

        if (featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE]) {
            items.push({
                name: 'Views',
                items: views.map((table) => ({
                    table: table,
                    icon: <IconBrackets />,
                })),
                emptyLabel: <span className="text-muted">No views found</span>,
                isLoading: databaseLoading,
            })
        }

        return items
    }

    return (
        <div
            className={clsx(
                `bg-bg-light space-y-px rounded border p-2 overflow-y-auto max-h-screen`,
                !collapsed ? 'min-w-80 flex-1' : 'flex-0'
            )}
        >
            {collapsed ? (
                <LemonButton icon={<IconDatabase />} onClick={() => setCollapsed(false)} />
            ) : (
                <>
                    <LemonButton
                        size="xsmall"
                        onClick={() => setCollapsed(true)}
                        fullWidth
                        sideIcon={<IconChevronDown className="rotate-90 text-xl" />}
                    >
                        <span className="uppercase text-muted-alt tracking-wider">Schemas</span>
                    </LemonButton>
                    <DatabaseTableTree onSelectRow={selectRow} items={treeItems()} selectedRow={selectedRow} />
                </>
            )}
        </div>
    )
}
