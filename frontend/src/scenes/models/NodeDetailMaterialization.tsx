import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils'

import { DataModelingJob } from '~/types'

import { STATUS_TAG_SETTINGS } from './constants'
import { nodeDetailSceneLogic, NodeDetailSceneLogicProps } from './nodeDetailSceneLogic'

function jobDuration(job: DataModelingJob): string | null {
    if (!job.last_run_at || !job.created_at) {
        return null
    }
    const start = new Date(job.created_at).getTime()
    const end = new Date(job.last_run_at).getTime()
    const seconds = (end - start) / 1000
    if (seconds < 0) {
        return null
    }
    return humanFriendlyDuration(seconds)
}

const COLUMNS: LemonTableColumns<DataModelingJob> = [
    {
        title: 'Status',
        key: 'status',
        width: 120,
        render: (_, job) => <LemonTag type={STATUS_TAG_SETTINGS[job.status] || 'default'}>{job.status}</LemonTag>,
    },
    {
        title: 'Started at',
        key: 'created_at',
        render: (_, job) =>
            job.created_at ? <TZLabel time={job.created_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" /> : '—',
    },
    {
        title: 'Duration',
        key: 'duration',
        render: (_, job) => {
            if (job.status === 'Running') {
                return '—'
            }
            return jobDuration(job) ?? '—'
        },
    },
    {
        title: 'Rows',
        key: 'rows_materialized',
        render: (_, job) => (job.rows_materialized > 0 ? job.rows_materialized.toLocaleString() : '—'),
    },
    {
        title: 'Error',
        key: 'error',
        render: (_, job) => {
            if (!job.error) {
                return '—'
            }
            const truncated = job.error.length > 80 ? job.error.slice(0, 80) + '…' : job.error
            return (
                <Tooltip title={job.error}>
                    <span className="text-danger font-mono text-xs">{truncated}</span>
                </Tooltip>
            )
        },
    },
]

export function NodeDetailMaterialization({ id }: NodeDetailSceneLogicProps): JSX.Element {
    const { materializationJobs, materializationJobsLoading } = useValues(nodeDetailSceneLogic({ id }))
    const { loadNextJobs, loadPreviousJobs } = useActions(nodeDetailSceneLogic({ id }))

    const hasNext = !!materializationJobs?.next
    const hasPrevious = !!materializationJobs?.previous

    return (
        <div className="space-y-2">
            <LemonLabel
                className="text-base font-semibold"
                info="History of scheduled materialization runs for this view"
            >
                Materialization
            </LemonLabel>
            <LemonTable
                columns={COLUMNS}
                dataSource={materializationJobs?.results ?? []}
                loading={materializationJobsLoading}
                size="small"
                noSortingCancellation
            />
            {(hasNext || hasPrevious) && (
                <div className="flex justify-end gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        disabled={!hasPrevious}
                        onClick={() => loadPreviousJobs()}
                    >
                        Previous
                    </LemonButton>
                    <LemonButton type="secondary" size="small" disabled={!hasNext} onClick={() => loadNextJobs()}>
                        Next
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
