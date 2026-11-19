import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { DestinationDeliveryFailureApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { JobLogsViewer } from '../../shared/components/JobLogsViewer'

export interface DestinationDeliveryFailuresTableProps {
    failures: DestinationDeliveryFailureApi[]
    loading: boolean
    windowDays: number | null
}

export function DestinationDeliveryFailuresTable({
    failures,
    loading,
    windowDays,
}: DestinationDeliveryFailuresTableProps): JSX.Element {
    return (
        <LemonTable
            dataSource={failures}
            loading={loading}
            rowKey={(failure) => failure.job_id}
            nouns={['failed delivery', 'failed deliveries']}
            emptyState={
                windowDays
                    ? `No failed deliveries in the last ${windowDays} days.`
                    : 'No failed deliveries in the last few days.'
            }
            columns={[
                {
                    title: 'Table',
                    key: 'table',
                    render: (_, failure) => (
                        <div className="flex flex-col items-start">
                            {failure.schema_id ? (
                                <Link
                                    className="font-semibold"
                                    to={urls.dataWarehouseSourceSchema(failure.source_id, failure.schema_id)}
                                    data-attr="warehouse-destination-failure-table-link"
                                >
                                    {failure.schema_name ?? 'Unknown table'}
                                </Link>
                            ) : (
                                <span className="font-semibold">Unknown table</span>
                            )}
                            <Link
                                className="text-xs text-muted"
                                to={urls.dataWarehouseSource(failure.source_id, 'syncs')}
                                data-attr="warehouse-destination-failure-source-link"
                            >
                                {failure.source_name}
                            </Link>
                        </div>
                    ),
                },
                {
                    title: 'Error',
                    key: 'error',
                    render: (_, failure) => (
                        <div className="flex flex-col items-start gap-1 py-1">
                            {failure.is_configuration_error ? (
                                <LemonTag type="danger">Destination settings</LemonTag>
                            ) : null}
                            <span className="font-mono text-xs whitespace-pre-wrap break-words select-text">
                                {failure.error}
                            </span>
                        </div>
                    ),
                },
                {
                    title: 'Started',
                    key: 'created_at',
                    width: 0,
                    render: (_, failure) => (
                        <TZLabel time={failure.created_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                    ),
                },
            ]}
            expandable={{
                expandedRowRender: (failure) =>
                    failure.schema_id ? (
                        <div className="p-4">
                            <JobLogsViewer
                                jobId={failure.job_id}
                                schemaId={failure.schema_id}
                                workflowRunId={failure.workflow_run_id}
                                createdAt={failure.created_at}
                                finishedAt={failure.finished_at}
                            />
                        </div>
                    ) : null,
                rowExpandable: (failure) => !!failure.schema_id,
                noIndent: true,
            }}
        />
    )
}
