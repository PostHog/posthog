import { useActions, useValues } from 'kea'

import { LemonSelect, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { computeJobDuration } from 'scenes/data-warehouse/saved_queries/materializationJobUtils'
import { urls } from 'scenes/urls'

import { STATUS_TAG_SETTINGS } from 'products/data_modeling/frontend/lineage/nodeStyles'

import { ModelRun, RUN_STATUSES, RUNS_PAGE_SIZE, modelsRunsLogic } from '../modelsRunsLogic'

export function ModelsRunsTab(): JSX.Element {
    const { runs, jobs, jobsLoading, statusFilter, page } = useValues(modelsRunsLogic)
    const { setStatusFilter, setPage } = useActions(modelsRunsLogic)

    return (
        <div className="flex flex-col gap-2">
            <LemonSelect
                size="small"
                value={statusFilter}
                onChange={setStatusFilter}
                options={[
                    { value: null, label: 'All statuses' },
                    ...RUN_STATUSES.map((status) => ({ value: status, label: status })),
                ]}
                data-attr="models-runs-status-filter"
            />
            <LemonTable
                dataSource={runs}
                loading={jobsLoading}
                rowKey={(run) => run.job.id}
                emptyState={statusFilter ? `No ${statusFilter.toLowerCase()} runs yet` : 'No runs yet'}
                columns={[
                    {
                        title: 'Model',
                        key: 'model',
                        render: (_, run: ModelRun) => {
                            if (!run.modelName) {
                                return <span className="text-muted">Deleted model</span>
                            }
                            return run.nodeId ? (
                                <Link to={urls.nodeDetail(run.nodeId, 'materialization')}>{run.modelName}</Link>
                            ) : (
                                run.modelName
                            )
                        },
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, { job }: ModelRun) => {
                            const tag = (
                                <LemonTag type={STATUS_TAG_SETTINGS[job.status] || 'default'}>{job.status}</LemonTag>
                            )
                            return job.error ? (
                                <Tooltip title={job.error} interactive>
                                    {tag}
                                </Tooltip>
                            ) : (
                                tag
                            )
                        },
                    },
                    {
                        title: 'Rows',
                        key: 'rows',
                        render: (_, { job }: ModelRun) =>
                            job.status === 'Completed' ? job.rows_materialized.toLocaleString() : '-',
                    },
                    {
                        title: 'Started',
                        key: 'started',
                        render: (_, { job }: ModelRun) => (
                            <TZLabel time={job.created_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                        ),
                    },
                    {
                        title: 'Duration',
                        key: 'duration',
                        render: (_, { job }: ModelRun) => computeJobDuration(job),
                    },
                ]}
                pagination={{
                    controlled: true,
                    pageSize: RUNS_PAGE_SIZE,
                    currentPage: page,
                    entryCount: jobs?.count ?? 0,
                    onForward: () => setPage(page + 1),
                    onBackward: () => setPage(page - 1),
                }}
            />
        </div>
    )
}
