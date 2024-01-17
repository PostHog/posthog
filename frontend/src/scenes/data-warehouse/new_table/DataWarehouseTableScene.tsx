import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DatawarehouseTableForm } from './DataWarehouseTableForm'
import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'

export const scene: SceneExport = {
    component: DataWarehouseTable,
    logic: dataWarehouseTableLogic,
}
export function DataWarehouseTable(): JSX.Element {
    const { isEditingTable, tableLoading, table } = useValues(dataWarehouseTableLogic)
    const { editingTable, loadTable, createTable } = useActions(dataWarehouseTableLogic)
    return (
        <>
            <PageHeader
                buttons={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            data-attr="cancel-table"
                            type="secondary"
                            loading={tableLoading}
                            onClick={() => {
                                if (isEditingTable) {
                                    editingTable(false)
                                    loadTable()
                                } else {
                                    router.actions.push(urls.dataWarehouse())
                                }
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="save-data-warehouse-table"
                            onClick={() => {
                                createTable(table)
                            }}
                            loading={tableLoading}
                        >
                            Save
                        </LemonButton>
                    </div>
                }
                caption={
                    <div>
                        External tables are supported through object storage systems like S3.{' '}
                        <Link
                            to="https://posthog.com/docs/data/data-warehouse#step-1-creating-a-bucket-in-s3"
                            target="_blank"
                        >
                            Learn how to set up your data
                        </Link>
                    </div>
                }
            />
            <DatawarehouseTableForm />
        </>
    )
}
