import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonInput, LemonTable } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { sourceManagementLogic } from '../logics/sourceManagementLogic'
import { SourceIcon, mapUrlToProvider } from './SourceIcon'

export function SelfManagedSourcesTable(): JSX.Element {
    const { filteredSelfManagedTables, searchTerm, databaseLoading } = useValues(sourceManagementLogic)
    const { deleteSelfManagedTable, refreshSelfManagedTableSchema, setSearchTerm } = useActions(sourceManagementLogic)

    return (
        <div>
            <div className="flex gap-2 justify-between items-center mb-4">
                <LemonInput type="search" placeholder="Search..." onChange={setSearchTerm} value={searchTerm} />
            </div>
            <LemonTable
                id="self-managed-sources"
                dataSource={filteredSelfManagedTables}
                loading={databaseLoading}
                pagination={{ pageSize: 10 }}
                scrollToTopOnPageChange={false}
                columns={[
                    {
                        width: 0,
                        render: (_, table) => <SourceIcon type={mapUrlToProvider(table.url_pattern)} />,
                    },
                    {
                        title: 'Source',
                        key: 'name',
                        render: (_, table) => (
                            <LemonTableLink
                                to={urls.dataWarehouseSource(`self-managed-${table.id}`)}
                                title={table.name}
                            />
                        ),
                    },
                    {
                        key: 'actions',
                        render: (_, table) => (
                            <div className="flex flex-row justify-end">
                                <LemonButton
                                    data-attr={`refresh-data-warehouse-${table.name}`}
                                    onClick={() => refreshSelfManagedTableSchema(table.id)}
                                >
                                    Update schema from source
                                </LemonButton>
                                <LemonButton
                                    status="danger"
                                    data-attr={`delete-data-warehouse-${table.name}`}
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Delete table?',
                                            description:
                                                'Table deletion cannot be undone. All views and joins related to this table will be deleted.',
                                            primaryButton: {
                                                children: 'Delete',
                                                status: 'danger',
                                                onClick: () => deleteSelfManagedTable(table.id),
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
