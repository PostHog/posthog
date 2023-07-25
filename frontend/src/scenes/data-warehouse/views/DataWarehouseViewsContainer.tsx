import { useActions, useValues } from 'kea'
import { DatabaseTables } from 'scenes/data-management/database/DatabaseTables'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { deleteWithUndo } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { DataWarehouseSceneRow } from '../types'
import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'
import { DataTableNode, HogQLQuery, NodeKind } from '~/queries/schema'
import { router } from 'kea-router'

export function DataWarehouseViewsContainer(): JSX.Element {
    const { views, dataWarehouseViewsLoading } = useValues(dataWarehouseViewsLogic)
    const { loadDataWarehouseViews } = useActions(dataWarehouseViewsLogic)
    const { currentTeamId } = useValues(teamLogic)
    return (
        <DatabaseTables
            tables={views}
            loading={dataWarehouseViewsLoading}
            renderRow={(row: DataWarehouseSceneRow) => {
                return (
                    <div className="px-4 py-3">
                        <div className="mt-2">
                            <span className="card-secondary">Columns</span>
                            <DatabaseTable table={row.name} tables={views} />
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
                                                deleteWithUndo({
                                                    endpoint: `projects/${currentTeamId}/warehouse_view`,
                                                    object: { name: warehouseView.name, id: warehouseView.id },
                                                    callback: loadDataWarehouseViews,
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
