import { LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { CHECK_STATUS_TAG_TYPES, byStatusAttention, checkRunDisplayName, runResultCell } from './checksConstants'
import type { DataQualityCheckRunApi } from './generated/api.schemas'

type CheckRunColumn = LemonTableColumn<DataQualityCheckRunApi, keyof DataQualityCheckRunApi | undefined>

const CHECK_COLUMN: CheckRunColumn = {
    title: 'Check',
    key: 'check',
    render: (_, run) => <span className="font-semibold">{checkRunDisplayName(run)}</span>,
}

const OUTCOME_COLUMNS: CheckRunColumn[] = [
    {
        title: 'Status',
        key: 'status',
        render: (_, run) => <LemonTag type={CHECK_STATUS_TAG_TYPES[run.status] ?? 'default'}>{run.status}</LemonTag>,
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
        title: 'Result',
        key: 'observed_value',
        render: (_, run) => {
            const { label, tooltip } = runResultCell(run)
            return tooltip ? (
                <Tooltip title={tooltip}>
                    <span>{label}</span>
                </Tooltip>
            ) : (
                label
            )
        },
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
]

interface CheckRunsTableProps {
    runs: DataQualityCheckRunApi[]
    loading?: boolean
    showCheck?: boolean
}

export function CheckRunsTable({ runs, loading, showCheck }: CheckRunsTableProps): JSX.Element {
    return (
        <LemonTable
            size="small"
            dataSource={showCheck ? [...runs].sort(byStatusAttention) : runs}
            loading={loading}
            nouns={['run', 'runs']}
            emptyState="No runs yet"
            columns={showCheck ? [CHECK_COLUMN, ...OUTCOME_COLUMNS] : OUTCOME_COLUMNS}
        />
    )
}
