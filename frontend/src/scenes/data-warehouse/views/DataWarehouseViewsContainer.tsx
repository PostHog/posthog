import { useActions, useValues } from 'kea'
import { DatabaseTables } from 'scenes/data-management/database/DatabaseTables'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonButton } from '@posthog/lemon-ui'
import { deleteWithUndo } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { DataWarehouseSceneRow } from '../types'
import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'

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
