import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDialog, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'

import { SSFDirectionEnumApi, SSFProtocolStatusEnumApi, SSFStreamStatusEnumApi } from '~/generated/core/api.schemas'

import { SSFSettingsLogicProps, ssfSettingsLogic } from './ssfSettingsLogic'

type Props = SSFSettingsLogicProps & { disabledReason?: string | null }

export function SSFStreams({ organizationId, disabledReason }: Props): JSX.Element {
    const logic = ssfSettingsLogic({ organizationId })
    const { streams, streamsLoading, streamsError, connections, configuration } = useValues(logic)
    const { loadStreams, openStream, openSubject, verifyStream, provisionStream, setStreamStatus, deleteStream } =
        useActions(logic)
    return (
        <section className="space-y-3" data-attr="ssf-streams">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <h3 className="mb-0">Streams</h3>
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="secondary"
                        disabledReason={disabledReason}
                        onClick={loadStreams}
                        data-attr="ssf-refresh-streams"
                    >
                        Refresh
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={
                            disabledReason ||
                            (!configuration?.enabled
                                ? 'Enable SSF first.'
                                : !connections?.length
                                  ? 'Add a connection first.'
                                  : undefined)
                        }
                        onClick={() => openStream()}
                        data-attr="ssf-add-stream"
                    >
                        Add stream
                    </LemonButton>
                </div>
            </div>
            {streamsError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadStreams }}>
                    Could not load SSF streams. Try again.
                </LemonBanner>
            ) : streams === null ? (
                <LemonSkeleton className="h-20" />
            ) : (
                <LemonTable
                    dataSource={streams}
                    loading={streamsLoading}
                    rowKey="id"
                    emptyState="No streams yet. Add a stream to subscribe to events or share events with a receiver."
                    columns={[
                        {
                            title: 'Stream',
                            key: 'name',
                            render: (_, stream) => (
                                <div className="min-w-0 space-y-1">
                                    <div className="font-semibold">{stream.description || 'Unnamed stream'}</div>
                                    <div className="text-secondary text-xs">
                                        {connections?.find((peer) => peer.id === stream.connection)?.name}
                                    </div>
                                    <div className="text-xs break-all">{stream.remote_stream_id || stream.id}</div>
                                    <div className="flex items-start gap-1 text-xs">
                                        <span className="min-w-0 break-all">{stream.endpoint_url}</span>
                                        <CopyToClipboardInline explicitValue={stream.endpoint_url} />
                                    </div>
                                    {stream.last_error && (
                                        <div className="text-danger text-xs break-words">{stream.last_error}</div>
                                    )}
                                </div>
                            ),
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, stream) => (
                                <div className="space-y-1">
                                    <LemonTag
                                        type={
                                            stream.status === SSFStreamStatusEnumApi.Enabled
                                                ? 'success'
                                                : stream.status === SSFStreamStatusEnumApi.Failed
                                                  ? 'danger'
                                                  : 'warning'
                                        }
                                    >
                                        {stream.status}
                                    </LemonTag>
                                    {stream.direction === SSFDirectionEnumApi.Incoming && (
                                        <div className="text-xs text-secondary">
                                            {stream.verification_pending ? (
                                                'Awaiting verification'
                                            ) : stream.last_verified_at ? (
                                                <TZLabel time={stream.last_verified_at} />
                                            ) : (
                                                'Not verified'
                                            )}
                                        </div>
                                    )}
                                    <div className="text-xs text-secondary">
                                        {stream.events_delivered.length}{' '}
                                        {stream.events_delivered.length === 1 ? 'event type' : 'event types'}
                                    </div>
                                </div>
                            ),
                        },
                        {
                            title: 'Actions',
                            key: 'actions',
                            render: (_, stream) => {
                                const pending =
                                    stream.status === SSFStreamStatusEnumApi.Failed ||
                                    stream.status === SSFStreamStatusEnumApi.Provisioning
                                const reason =
                                    disabledReason ||
                                    (stream.is_busy ? 'This stream has an operation in progress.' : undefined)
                                return (
                                    <div className="flex flex-wrap gap-1">
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            disabledReason={reason}
                                            onClick={() => openStream(stream)}
                                            data-attr="ssf-edit-stream"
                                        >
                                            Edit
                                        </LemonButton>
                                        {stream.direction === SSFDirectionEnumApi.Incoming && (
                                            <LemonButton
                                                size="small"
                                                type="secondary"
                                                disabledReason={reason}
                                                onClick={() => provisionStream({ id: stream.id })}
                                                data-attr="ssf-provision-stream"
                                            >
                                                {pending ? 'Retry setup' : 'Reconnect'}
                                            </LemonButton>
                                        )}
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            disabledReason={
                                                reason || (pending ? 'Finish setting up this stream first.' : undefined)
                                            }
                                            onClick={() => verifyStream({ id: stream.id })}
                                            data-attr="ssf-verify-stream"
                                        >
                                            Verify
                                        </LemonButton>
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            disabledReason={
                                                reason || (pending ? 'Finish setting up this stream first.' : undefined)
                                            }
                                            onClick={() => openSubject(stream.id)}
                                            data-attr="ssf-stream-subjects"
                                        >
                                            Subjects
                                        </LemonButton>
                                        {!pending && (
                                            <LemonButton
                                                size="small"
                                                type="secondary"
                                                disabledReason={reason}
                                                onClick={() =>
                                                    setStreamStatus({
                                                        id: stream.id,
                                                        status:
                                                            stream.status === SSFStreamStatusEnumApi.Enabled
                                                                ? SSFProtocolStatusEnumApi.Paused
                                                                : SSFProtocolStatusEnumApi.Enabled,
                                                    })
                                                }
                                                data-attr="ssf-stream-status"
                                            >
                                                {stream.status === SSFStreamStatusEnumApi.Enabled ? 'Pause' : 'Enable'}
                                            </LemonButton>
                                        )}
                                        <LemonButton
                                            size="small"
                                            status="danger"
                                            disabledReason={reason}
                                            data-attr="ssf-delete-stream"
                                            onClick={() =>
                                                LemonDialog.open({
                                                    title: 'Delete this stream?',
                                                    description:
                                                        'This removes the stream and its pending outgoing events. For managed incoming streams, PostHog also requests deletion at the transmitter.',
                                                    primaryButton: {
                                                        children: 'Delete stream',
                                                        status: 'danger',
                                                        onClick: () => deleteStream({ id: stream.id }),
                                                    },
                                                    secondaryButton: { children: 'Cancel' },
                                                })
                                            }
                                        >
                                            Delete
                                        </LemonButton>
                                    </div>
                                )
                            },
                        },
                    ]}
                />
            )}
        </section>
    )
}
