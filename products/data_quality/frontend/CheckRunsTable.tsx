import { LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { CHECK_STATUS_TAG_TYPES } from './checksConstants'
import type { DataQualityCheckRunApi } from './generated/api.schemas'

interface CheckRunsTableProps {
    runs: DataQualityCheckRunApi[]
    loading?: boolean
}

export function CheckRunsTable({ runs, loading }: CheckRunsTableProps): JSX.Element {
    return (
        <LemonTable
            size="small"
            dataSource={runs}
            loading={loading}
            nouns={['run', 'runs']}
            emptyState="No runs yet"
            columns={[
                {
                    title: 'Status',
                    key: 'status',
                    render: (_, run) => (
                        <LemonTag type={CHECK_STATUS_TAG_TYPES[run.status] ?? 'default'}>{run.status}</LemonTag>
                    ),
                },
                {
                    title: 'Started',
                    key: 'started_at',
                    render: (_, run) => (run.started_at ? <TZLabel time={run.started_at} /> : '-'),
                },
                {
                    title: 'Duration',
                    key: 'duration_ms',
                    render: (_, run) =>
                        run.duration_ms === null ? '-' : humanFriendlyDuration(run.duration_ms / 1000, { maxUnits: 2 }),
                },
                {
                    title: 'Observed value',
                    key: 'observed_value',
                    render: (_, run) => (run.observed_value === null ? '-' : humanFriendlyNumber(run.observed_value)),
                },
                {
                    title: 'Failed rows',
                    key: 'failed_row_count',
                    render: (_, run) =>
                        run.failed_row_count === null ? '-' : humanFriendlyNumber(run.failed_row_count),
                },
                {
                    title: 'Error',
                    key: 'error',
                    render: (_, run) =>
                        run.error ? (
                            <Tooltip title={run.error}>
                                <span className="text-danger truncate max-w-xs inline-block">{run.error}</span>
                            </Tooltip>
                        ) : (
                            '-'
                        ),
                },
            ]}
        />
    )
}
