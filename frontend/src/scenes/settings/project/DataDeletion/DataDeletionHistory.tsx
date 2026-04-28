import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
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

function DetailField({
    label,
    children,
    fullWidth,
}: {
    label: string
    children: React.ReactNode
    fullWidth?: boolean
}): JSX.Element {
    return (
        <div className={fullWidth ? 'col-span-full' : undefined}>
            <div className="text-muted-alt mb-1 text-[11px] font-medium uppercase tracking-wider">{label}</div>
            <div className="text-sm">{children}</div>
        </div>
    )
}

function ExpandedRow({ row }: { row: DataDeletionRequest }): JSX.Element {
    const isAllEvents = row.delete_all_events
    const hasEvents = row.events.length > 0
    const hasProperties = row.properties.length > 0
    const hasPredicate = !!row.hogql_predicate
    const hasNotes = !!row.notes

    return (
        <div className="bg-surface-primary flex flex-col gap-4 p-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <DetailField label="Time range">
                    <TZLabel time={row.start_time} timestampStyle="absolute" />
                    <span className="text-secondary mx-1">→</span>
                    <TZLabel time={row.end_time} timestampStyle="absolute" />
                </DetailField>
                <DetailField label="Matched events at submit time">
                    {row.count === null ? (
                        <span className="text-muted">Not yet computed</span>
                    ) : (
                        row.count.toLocaleString()
                    )}
                </DetailField>
            </div>

            {row.request_type === 'event_removal' && (
                <DetailField label="Events" fullWidth>
                    {isAllEvents ? (
                        <span className="text-secondary italic">All events in the time range</span>
                    ) : hasEvents ? (
                        <div className="flex flex-wrap gap-1">
                            {row.events.map((name) => (
                                <LemonTag key={name} type="completion">
                                    {name}
                                </LemonTag>
                            ))}
                        </div>
                    ) : (
                        <span className="text-muted">Predicate-matched events only</span>
                    )}
                </DetailField>
            )}

            {row.request_type === 'property_removal' && hasProperties && (
                <DetailField label="Properties to remove" fullWidth>
                    <div className="flex flex-wrap gap-1">
                        {row.properties.map((name) => (
                            <LemonTag key={name} type="completion">
                                {name}
                            </LemonTag>
                        ))}
                    </div>
                </DetailField>
            )}

            {hasPredicate && (
                <DetailField label="SQL expression" fullWidth>
                    <CodeSnippet language={Language.SQL} compact wrap>
                        {row.hogql_predicate}
                    </CodeSnippet>
                </DetailField>
            )}

            {hasNotes && (
                <DetailField label="Notes for reviewers" fullWidth>
                    <p className="whitespace-pre-wrap">{row.notes}</p>
                </DetailField>
            )}
        </div>
    )
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
                    expandedRowRender: (row) => <ExpandedRow row={row} />,
                    noIndent: true,
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
