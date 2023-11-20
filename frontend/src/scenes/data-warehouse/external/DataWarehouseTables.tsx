import { useActions, useValues } from 'kea'
import { DatabaseTables } from 'scenes/data-management/database/DatabaseTables'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonButton } from '@posthog/lemon-ui'
import { deleteWithUndo } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { DataWarehouseSceneRow } from '../types'

export function DataWarehouseTablesContainer(): JSX.Element {
    const { tables, dataWarehouseLoading } = useValues(dataWarehouseSceneLogic)
    const { loadDataWarehouse } = useActions(dataWarehouseSceneLogic)
    const { currentTeamId } = useValues(teamLogic)
    return (
        <DatabaseTables
            tables={tables}
            loading={dataWarehouseLoading}
            renderRow={(row: DataWarehouseSceneRow) => {
                return (
                    <div className="px-4 py-3">
                        <div className="flex flex-col">
                            <span className="card-secondary mt-2">Files URL pattern</span>
                            <span>{row.url_pattern}</span>

                            <span className="card-secondary mt-2">File format</span>
                            <span>{row.format}</span>
                        </div>

                        <div className="mt-2">
                            <span className="card-secondary">Columns</span>
                            <DatabaseTable table={row.name} tables={tables} />
                        </div>
                    </div>
                )
            }}
            extraColumns={[
                {
                    width: 0,
                    render: function Render(_, warehouseTable: DataWarehouseSceneRow) {
                        return (
                            <More
                                overlay={
                                    <>
                                        <LemonButton
                                            status="danger"
                                            onClick={() => {
                                                void deleteWithUndo({
                                                    endpoint: `projects/${currentTeamId}/warehouse_tables`,
                                                    object: { name: warehouseTable.name, id: warehouseTable.id },
                                                    callback: loadDataWarehouse,
                                                })
                                            }}
                                            fullWidth
                                        >
                                            Delete table
                                        </LemonButton>
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
