import { useActions, useAsyncActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonTable } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { sourceManagementLogic } from '../logics/sourceManagementLogic'
import { SourceIcon, mapUrlToProvider } from './SourceIcon'

export function SelfManagedSourcesTable(): JSX.Element {
    const { filteredSelfManagedTables, searchTerm, databaseLoading, pendingSelfManagedTableIdsLoading } =
        useValues(sourceManagementLogic)
    const { deleteSelfManagedTable, refreshSelfManagedTableSchema, setSearchTerm } = useActions(sourceManagementLogic)
    const { deleteSelfManagedTables } = useAsyncActions(sourceManagementLogic)

    return (
        <div>
            <div className="flex gap-2 justify-between items-center mb-4">
                <LemonInput type="search" placeholder="Search..." onChange={setSearchTerm} value={searchTerm} />
            </div>
            <LemonTable
                id="self-managed-sources"
                dataSource={pendingSelfManagedTableIdsLoading ? [] : filteredSelfManagedTables}
                loading={databaseLoading || pendingSelfManagedTableIdsLoading}
                pagination={{ pageSize: 10 }}
                scrollToTopOnPageChange={false}
                bulkSelection={{
                    getKey: (table) => table.id,
                    rowAriaLabel: (table) => `Select ${table.name}`,
                    noun: ['table', 'tables'],
                    clearSelectionKey: searchTerm,
                    barClassName: 'mb-2',
                    renderActions: (ctx) => (
                        <LemonButton
                            size="small"
                            type="primary"
                            status="danger"
                            icon={<IconTrash />}
                            data-attr="self-managed-tables-bulk-delete"
                            onClick={() =>
                                LemonDialog.open({
                                    title: `Delete ${pluralize(ctx.selectedCount, 'table', 'tables')}?`,
                                    description: `Table deletion cannot be undone. All views and joins related to ${pluralize(ctx.selectedCount, 'this table', 'these tables', false)} will be deleted.`,
                                    shouldAwaitSubmit: true,
                                    primaryButton: {
                                        children: 'Delete',
                                        status: 'danger',
                                        'data-attr': 'self-managed-tables-bulk-delete-confirm',
                                        onClick: async () => {
                                            const tableIds = ctx.selectedKeys
                                            ctx.clearSelection()
                                            await deleteSelfManagedTables(tableIds)
                                        },
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                            }
                        >
                            Delete
                        </LemonButton>
                    ),
                }}
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
