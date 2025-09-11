import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonInput, LemonTable } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { DataWarehouseSourceIcon, mapUrlToProvider } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { DatabaseSchemaDataWarehouseTable } from '~/queries/schema/schema-general'

import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'

export function DataWarehouseSelfManagedSourcesTable(): JSX.Element {
    const { filteredSelfManagedTables, searchTerm } = useValues(dataWarehouseSettingsLogic)
    const { deleteSelfManagedTable, refreshSelfManagedTableSchema, setSearchTerm } =
        useActions(dataWarehouseSettingsLogic)

    return (
        <div>
            <div className="flex gap-2 justify-between items-center mb-4">
                <LemonInput type="search" placeholder="Search..." onChange={setSearchTerm} value={searchTerm} />
            </div>
            <LemonTable
                id="self-managed-sources"
                dataSource={filteredSelfManagedTables}
                pagination={{ pageSize: 10 }}
                columns={[
                    {
                        width: 0,
                        render: (_, item: DatabaseSchemaDataWarehouseTable) => (
                            <DataWarehouseSourceIcon type={mapUrlToProvider(item.url_pattern)} />
                        ),
                    },
                    {
                        title: 'Source',
                        dataIndex: 'name',
                        key: 'name',
                        render: (_, item: DatabaseSchemaDataWarehouseTable) => (
                            <LemonTableLink
                                to={urls.dataWarehouseSource(`self-managed-${item.id}`)}
                                title={item.name}
                            />
                        ),
                    },
                    {
                        key: 'actions',
                        render: (_, item: DatabaseSchemaDataWarehouseTable) => (
                            <div className="flex flex-row justify-end">
                                <LemonButton
                                    data-attr={`refresh-data-warehouse-${item.name}`}
                                    key={`refresh-data-warehouse-${item.name}`}
                                    onClick={() => refreshSelfManagedTableSchema(item.id)}
                                >
                                    Update schema from source
                                </LemonButton>
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
                        ),
                    },
                ]}
            />
        </div>
    )
}
