import { IconBrackets, IconDatabase } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DatabaseTableTree, TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { ViewLinkModal } from '../ViewLinkModal'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { TableData } from './TableData'

export const DataWarehouseTables = (): JSX.Element => {
    return (
        <>
            <div className="grid md:grid-cols-3">
                <div className="sm:col-span-3 md:col-span-1 max-h-160">
                    <DatabaseTableTreeWithItems />
                </div>
                <TableData />
            </div>
            <ViewLinkModal />
        </>
    )
}

interface DatabaseTableTreeProps {
    inline?: boolean
}

export const DatabaseTableTreeWithItems = ({ inline }: DatabaseTableTreeProps): JSX.Element => {
    const {
        externalTablesBySourceType,
        dataWarehouseLoading,
        posthogTables,
        databaseLoading,
        savedQueriesFormatted,
        selectedRow,
        dataWarehouseSavedQueriesLoading,
    } = useValues(dataWarehouseSceneLogic)
    const { selectRow } = useActions(dataWarehouseSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const treeItems = (): TreeItem[] => {
        if (inline) {
            const items: TreeItem[] = [
                {
                    name: 'External',
                    items: Object.keys(externalTablesBySourceType).map((source_type) => ({
                        name: source_type,
                        items: externalTablesBySourceType[source_type].map((table) => ({
                            name: table.name,
                            items: table.columns.map((column) => ({
                                name: column.key,
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
                    isLoading: dataWarehouseLoading,
                },
                {
                    name: 'PostHog',
                    items: posthogTables.map((table) => ({
                        name: table.name,
                        items: table.columns.map((column) => ({
                            name: column.key,
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
                    items: savedQueriesFormatted.map((table) => ({
                        name: table.name,
                        items: table.columns.map((column) => ({
                            name: column.key,
                            type: column.type,
                            icon: <IconDatabase />,
                        })),
                    })),
                    emptyLabel: <span className="text-muted">No views found</span>,
                    isLoading: dataWarehouseSavedQueriesLoading,
                })
            }

            return items
        }

        const items: TreeItem[] = [
            {
                name: 'External',
                items: Object.keys(externalTablesBySourceType).map((source_type) => ({
                    name: source_type,
                    items: externalTablesBySourceType[source_type].map((table) => ({
                        table: table,
                        icon: <IconDatabase />,
                    })),
                })),
                emptyLabel: (
                    <span className="text-muted">
                        No tables found. <Link to={urls.dataWarehouseTable()}>Link source</Link>
                    </span>
                ),
                isLoading: dataWarehouseLoading,
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
                items: savedQueriesFormatted.map((table) => ({
                    table: table,
                    icon: <IconBrackets />,
                })),
                emptyLabel: <span className="text-muted">No views found</span>,
                isLoading: dataWarehouseSavedQueriesLoading,
            })
        }

        return items
    }

    return <DatabaseTableTree onSelectRow={selectRow} items={treeItems()} selectedRow={selectedRow} />
}
