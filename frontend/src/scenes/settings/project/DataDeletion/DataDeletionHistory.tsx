import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { DataDeletionRequest, DataDeletionStatus } from './dataDeletionLogic'
import { dataDeletionLogic } from './dataDeletionLogic'

const STATUS_TAG_TYPE: Record<DataDeletionStatus, LemonTagType> = {
    draft: 'muted',
    pending: 'warning',
    approved: 'primary',
    in_progress: 'primary',
    queued: 'primary',
    completed: 'success',
    failed: 'danger',
}

const STATUS_LABEL: Record<DataDeletionStatus, string> = {
    draft: 'Draft',
    pending: 'Pending review',
    approved: 'Approved',
    in_progress: 'In progress',
    queued: 'Queued for deletion',
    completed: 'Completed',
    failed: 'Failed',
}

function summarize(row: DataDeletionRequest): string {
    const typeLabel = row.request_type === 'event_removal' ? 'Delete events' : 'Remove properties'
    const eventsLabel = row.delete_all_events
        ? 'all events'
        : row.events.length > 0
          ? row.events.length === 1
              ? row.events[0]
              : `${row.events.length} event names`
          : 'predicate-matched events'
    if (row.request_type === 'property_removal') {
        return `Remove ${row.properties.length} propert${row.properties.length === 1 ? 'y' : 'ies'} from ${eventsLabel}`
    }
    return `${typeLabel}: ${eventsLabel}`
}

export function DataDeletionHistory(): JSX.Element {
    const { deletionRequests, deletionRequestsLoading } = useValues(dataDeletionLogic)
    const { cancelRequest, loadDeletionRequests } = useActions(dataDeletionLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-start justify-between gap-2">
                <LemonBanner type="info" className="grow">
                    Approved requests are picked up by our deletion worker within 10 minutes. Completed deletions are
                    irreversible.
                </LemonBanner>
                <LemonButton
                    icon={<IconRefresh />}
                    type="secondary"
                    size="small"
                    onClick={() => loadDeletionRequests()}
                    loading={deletionRequestsLoading}
                    tooltip="Refresh"
                />
            </div>
            <LemonTable<DataDeletionRequest>
                dataSource={deletionRequests}
                loading={deletionRequestsLoading}
                rowKey="id"
                emptyState="No data deletion requests yet."
                expandable={{
                    expandedRowRender: (row) => (
                        <div className="flex flex-col gap-1 p-2 text-sm">
                            <div>
                                <b>Time range:</b> <TZLabel time={row.start_time} timestampStyle="absolute" /> &rarr;{' '}
                                <TZLabel time={row.end_time} timestampStyle="absolute" />
                            </div>
                            {row.events.length > 0 && (
                                <div>
                                    <b>Events:</b> {row.events.join(', ')}
                                </div>
                            )}
                            {row.properties.length > 0 && (
                                <div>
                                    <b>Properties:</b> {row.properties.join(', ')}
                                </div>
                            )}
                            {row.hogql_predicate && (
                                <div>
                                    <b>HogQL predicate:</b> <code>{row.hogql_predicate}</code>
                                </div>
                            )}
                            {row.notes && (
                                <div>
                                    <b>Notes:</b> {row.notes}
                                </div>
                            )}
                        </div>
                    ),
                }}
                columns={[
                    { title: 'Summary', render: (_, row) => summarize(row) },
                    {
                        title: 'Type',
                        dataIndex: 'request_type',
                        render: (value) => <LemonTag>{value === 'event_removal' ? 'Events' : 'Properties'}</LemonTag>,
                    },
                    {
                        title: 'Events',
                        dataIndex: 'count',
                        align: 'center',
                        tooltip: 'Estimated matched events at submit time. Dashes mean it has not been computed yet.',
                        render: (value) => (value === null ? '—' : (value as number).toLocaleString()),
                    },
                    {
                        title: 'Status',
                        dataIndex: 'status',
                        render: (value) => {
                            const status = value as DataDeletionStatus
                            return <LemonTag type={STATUS_TAG_TYPE[status]}>{STATUS_LABEL[status]}</LemonTag>
                        },
                    },
                    {
                        title: 'Submitted',
                        dataIndex: 'created_at',
                        align: 'center',
                        render: (value) => <TZLabel time={value as string} timestampStyle="absolute" />,
                    },
                    {
                        title: 'By',
                        dataIndex: 'created_by',
                        render: (value) => {
                            const user = value as DataDeletionRequest['created_by']
                            return user ? user.first_name || user.email : '—'
                        },
                    },
                    {
                        title: '',
                        render: (_, row) =>
                            row.status === 'pending' ? (
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    status="danger"
                                    onClick={() => cancelRequest(row.id)}
                                >
                                    Cancel
                                </LemonButton>
                            ) : null,
                    },
                ]}
            />
        </div>
    )
}
