import { useValues } from 'kea'
import { DatabaseTables } from 'scenes/data-management/database/DatabaseTables'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'

export function DataWarehouseTablesContainer(): JSX.Element {
    const { tables, dataWarehouseLoading } = useValues(dataWarehouseSceneLogic)
    return <DatabaseTables tables={tables} loading={dataWarehouseLoading} />
}
