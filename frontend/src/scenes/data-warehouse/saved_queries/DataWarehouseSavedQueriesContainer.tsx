import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { DatabaseTables } from 'scenes/data-management/database/DatabaseTables'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DataTableNode, HogQLQuery, NodeKind } from '~/queries/schema'

import { DataWarehouseSceneRow } from '../types'
import { dataWarehouseSavedQueriesLogic } from './dataWarehouseSavedQueriesLogic'

export function DataWarehouseSavedQueriesContainer(): JSX.Element {
    const { savedQueries, dataWarehouseSavedQueriesLoading } = useValues(dataWarehouseSavedQueriesLogic)
    const { loadDataWarehouseSavedQueries } = useActions(dataWarehouseSavedQueriesLogic)
    const { currentTeamId } = useValues(teamLogic)

    return (
        <DatabaseTables
            tables={savedQueries}
            loading={dataWarehouseSavedQueriesLoading}
            renderRow={(row: DataWarehouseSceneRow) => {
                return (
                    <div className="px-4 py-3">
                        <div className="mt-2">
                            <span className="card-secondary">Columns</span>
                            <DatabaseTable table={row.name} tables={savedQueries} />
                        </div>
                    </div>
                )
            }}
            columns={[
                {
                    title: 'View',
                    key: 'name',
                    dataIndex: 'name',
                    render: function RenderTable(table, obj: DataWarehouseSceneRow) {
                        const query: DataTableNode = {
                            kind: NodeKind.DataTableNode,
                            full: true,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: `SELECT ${obj.columns
                                    .filter(({ table, fields, chain }) => !table && !fields && !chain)
                                    .map(({ key }) => key)} FROM ${table} LIMIT 100`,
                            },
                        }
                        return (
                            <div className="flex">
                                <Link to={urls.insightNew(undefined, undefined, JSON.stringify(query))}>
                                    <code>{table}</code>
                                </Link>
                            </div>
                        )
                    },
                },
            ]}
            extraColumns={[
                {
                    width: 0,
                    render: function Render(_, warehouseView: DataWarehouseSceneRow) {
                        return (
                            <More
                                overlay={
                                    <>
                                        <LemonButton
                                            status="danger"
                                            onClick={() => {
                                                void deleteWithUndo({
                                                    endpoint: `projects/${currentTeamId}/warehouse_saved_queries`,
                                                    object: { name: warehouseView.name, id: warehouseView.id },
                                                    callback: loadDataWarehouseSavedQueries,
                                                })
                                            }}
                                            fullWidth
                                        >
                                            Delete view
                                        </LemonButton>
                                        {warehouseView.query && (
                                            <LemonButton
                                                onClick={() => {
                                                    const query: DataTableNode = {
                                                        kind: NodeKind.DataTableNode,
                                                        full: true,
                                                        source: warehouseView.query as HogQLQuery,
                                                    }
                                                    router.actions.push(
                                                        urls.insightNew(undefined, undefined, JSON.stringify(query))
                                                    )
                                                }}
                                                fullWidth
                                            >
                                                View definition
                                            </LemonButton>
                                        )}
                                    </>
                                }
                            />
                        )
                    },
                },
            ]}
        />
    )
}
