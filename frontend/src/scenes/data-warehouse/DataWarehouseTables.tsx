import { useValues } from 'kea'
import { DatabaseTables } from 'scenes/data-management/database/DatabaseTables'
import { DataWarehouseSceneRow, dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'

export function DataWarehouseTablesContainer(): JSX.Element {
    const { tables, dataWarehouseLoading } = useValues(dataWarehouseSceneLogic)
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
        />
    )
}
