import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDialog, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { SSFDirectionEnumApi } from '~/generated/core/api.schemas'

import { SSFSettingsLogicProps, ssfSettingsLogic } from './ssfSettingsLogic'

type Props = SSFSettingsLogicProps & { disabledReason?: string | null }

export function SSFConnections({ organizationId, disabledReason }: Props): JSX.Element {
    const logic = ssfSettingsLogic({ organizationId })
    const { connections, connectionsLoading, connectionsError } = useValues(logic)
    const { loadConnections, openConnection, deleteConnection, refreshConnection, toggleConnection, rotateToken } =
        useActions(logic)
    return (
        <section className="space-y-3" data-attr="ssf-connections">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <h3 className="mb-0">Connections</h3>
                <LemonButton
                    type="primary"
                    disabledReason={disabledReason}
                    onClick={() => openConnection()}
                    data-attr="ssf-add-connection"
                >
                    Add connection
                </LemonButton>
            </div>
            {connectionsError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadConnections }}>
                    Could not load SSF connections. Try again.
                </LemonBanner>
            ) : connections === null ? (
                <LemonSkeleton className="h-20" />
            ) : (
                <LemonTable
                    loading={connectionsLoading}
                    dataSource={connections}
                    rowKey="id"
                    emptyState="No connections yet. Add a transmitter to receive events, or a receiver to share events."
                    columns={[
                        {
                            title: 'Connection',
                            key: 'name',
                            render: (_, peer) => (
                                <div className="min-w-0 space-y-1">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <span className="font-semibold">{peer.name}</span>
                                        <LemonTag>
                                            {peer.direction === SSFDirectionEnumApi.Incoming ? 'Incoming' : 'Outgoing'}
                                        </LemonTag>
                                    </div>
                                    <div className="text-secondary text-xs break-all">
                                        {peer.issuer || peer.audience}
                                    </div>
                                    {peer.direction === SSFDirectionEnumApi.Incoming && !peer.has_remote_token && (
                                        <div className="text-warning text-xs">
                                            Add an API token to manage incoming streams.
                                        </div>
                                    )}
                                </div>
                            ),
                        },
                        { title: 'Streams', dataIndex: 'stream_count' },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, peer) => (
                                <LemonTag type={peer.enabled ? 'success' : 'default'}>
                                    {peer.enabled ? 'Enabled' : 'Disabled'}
                                </LemonTag>
                            ),
                        },
                        {
                            title: 'Actions',
                            key: 'actions',
                            render: (_, peer) => (
                                <div className="flex flex-wrap gap-1">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        disabledReason={disabledReason}
                                        onClick={() => openConnection(peer)}
                                        data-attr="ssf-edit-connection"
                                    >
                                        Edit
                                    </LemonButton>
                                    {peer.direction === SSFDirectionEnumApi.Incoming ? (
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            disabledReason={disabledReason}
                                            onClick={() => refreshConnection({ id: peer.id })}
                                            data-attr="ssf-refresh-connection"
                                        >
                                            Refresh discovery
                                        </LemonButton>
                                    ) : (
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            disabledReason={disabledReason}
                                            data-attr="ssf-transmitter-credential"
                                            onClick={() =>
                                                LemonDialog.open({
                                                    title: peer.has_management_token
                                                        ? 'Replace the management credential?'
                                                        : 'Create a management credential?',
                                                    description:
                                                        'Replacing a credential stops the previous one from working. Update this receiver with the new credential.',
                                                    primaryButton: {
                                                        children: peer.has_management_token
                                                            ? 'Replace credential'
                                                            : 'Create credential',
                                                        onClick: () => rotateToken({ id: peer.id }),
                                                    },
                                                    secondaryButton: { children: 'Cancel' },
                                                })
                                            }
                                        >
                                            {peer.has_management_token ? 'Replace credential' : 'Create credential'}
                                        </LemonButton>
                                    )}
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        disabledReason={disabledReason}
                                        onClick={() => toggleConnection({ connection: peer })}
                                        data-attr="ssf-toggle-connection"
                                    >
                                        {peer.enabled ? 'Disable' : 'Enable'}
                                    </LemonButton>
                                    <LemonButton
                                        size="small"
                                        status="danger"
                                        disabledReason={disabledReason}
                                        data-attr="ssf-delete-connection"
                                        onClick={() =>
                                            LemonDialog.open({
                                                title: 'Delete this connection?',
                                                description:
                                                    'This disconnects the service and removes its streams. Incoming streams managed by PostHog are also removed from the transmitter when API credentials are available.',
                                                primaryButton: {
                                                    children: 'Delete connection',
                                                    status: 'danger',
                                                    onClick: () => deleteConnection({ id: peer.id }),
                                                },
                                                secondaryButton: { children: 'Cancel' },
                                            })
                                        }
                                    >
                                        Delete
                                    </LemonButton>
                                </div>
                            ),
                        },
                    ]}
                />
            )}
        </section>
    )
}
