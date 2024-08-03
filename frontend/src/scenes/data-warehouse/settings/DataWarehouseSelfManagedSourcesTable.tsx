import { LemonButton, LemonDialog, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { DatabaseSchemaDataWarehouseTable } from '~/queries/schema'

import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'

export function DataWarehouseSelfManagedSourcesTable(): JSX.Element {
    const { selfManagedTables } = useValues(dataWarehouseSettingsLogic)
    const { deleteSelfManagedTable } = useActions(dataWarehouseSettingsLogic)

    return (
        <LemonTable
            dataSource={selfManagedTables}
            pagination={{ pageSize: 10 }}
            columns={[
                {
                    title: 'Name',
                    dataIndex: 'name',
                    key: 'name',
                },
                {
                    key: 'actions',
                    render: (_, item: DatabaseSchemaDataWarehouseTable) => {
                        return (
                            <div className="flex flex-row justify-end">
                                <LemonButton
                                    status="danger"
                                    data-attr={`delete-data-warehouse-${item.name}`}
                                    key={`delete-data-warehouse-${item.name}`}
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Delete table?',
                                            description:
                                                'Table deletion cannot be undone. All views and joins related to this table will be deleted.',

                                            primaryButton: {
                                                children: 'Delete',
                                                status: 'danger',
                                                onClick: () => {
                                                    deleteSelfManagedTable(item.id)
                                                },
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                            },
                                        })
                                    }}
                                >
                                    Delete
                                </LemonButton>
                            </div>
                        )
                    },
                },
            ]}
        />
    )
}
