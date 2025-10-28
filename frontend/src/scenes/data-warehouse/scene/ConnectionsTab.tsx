import { useActions, useValues } from 'kea'

import { IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { WarehouseConnection } from '~/types'

import { warehouseConnectionsLogic } from '../connections/warehouseConnectionsLogic'
import { WarehouseConnectionModal } from '../connections/WarehouseConnectionModal'

export function ConnectionsTab(): JSX.Element {
    const { connections, connectionsLoading, modalOpen } = useValues(warehouseConnectionsLogic)
    const { setModalOpen, deleteConnection, testConnection } = useActions(warehouseConnectionsLogic)

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <div>
                    <h2 className="mb-2">Warehouse Connections</h2>
                    <p className="text-muted">
                        Connect external data warehouses to query data directly without syncing to PostHog.
                    </p>
                </div>
                <LemonButton type="primary" icon={<IconPlus />} onClick={() => setModalOpen(true)}>
                    New connection
                </LemonButton>
            </div>

            <LemonTable
                dataSource={connections}
                loading={connectionsLoading}
                columns={[
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, connection: WarehouseConnection) => (
                            <div>
                                <div className="font-medium">{connection.name}</div>
                                <div className="text-muted text-xs">{connection.provider}</div>
                            </div>
                        ),
                    },
                    {
                        title: 'Mode',
                        key: 'mode',
                        render: (_, connection: WarehouseConnection) => (
                            <LemonTag
                                type={
                                    connection.mode === 'direct'
                                        ? 'success'
                                        : connection.mode === 'hybrid'
                                        ? 'warning'
                                        : 'default'
                                }
                            >
                                {connection.mode}
                            </LemonTag>
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, connection: WarehouseConnection) => (
                            <div className="flex items-center gap-2">
                                <LemonTag type={connection.connection_status === 'healthy' ? 'success' : 'danger'}>
                                    {connection.connection_status}
                                </LemonTag>
                                {connection.last_tested_at && (
                                    <span className="text-xs text-muted">
                                        Last tested: {new Date(connection.last_tested_at).toLocaleString()}
                                    </span>
                                )}
                            </div>
                        ),
                    },
                    {
                        title: 'Active',
                        key: 'is_active',
                        render: (_, connection: WarehouseConnection) => (
                            <LemonTag type={connection.is_active ? 'success' : 'default'}>
                                {connection.is_active ? 'Active' : 'Inactive'}
                            </LemonTag>
                        ),
                    },
                    {
                        title: 'Actions',
                        key: 'actions',
                        render: (_, connection: WarehouseConnection) => (
                            <div className="flex gap-2">
                                <LemonButton
                                    size="small"
                                    icon={<IconRefresh />}
                                    onClick={() => testConnection(connection.id)}
                                >
                                    Test
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    status="danger"
                                    icon={<IconTrash />}
                                    onClick={() => deleteConnection(connection.id)}
                                />
                            </div>
                        ),
                    },
                ]}
                emptyState={
                    <div className="text-center py-8">
                        <h3 className="mb-2">No warehouse connections yet</h3>
                        <p className="text-muted mb-4">
                            Connect your data warehouse to query it directly alongside PostHog data.
                        </p>
                        <LemonButton type="primary" icon={<IconPlus />} onClick={() => setModalOpen(true)}>
                            Add your first connection
                        </LemonButton>
                    </div>
                }
            />

            {modalOpen && <WarehouseConnectionModal />}
        </div>
    )
}
