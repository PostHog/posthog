import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjsUtcToTimezone } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { DataModelingJob, LogEntryLevel } from '~/types'

import { STATUS_TAG_SETTINGS } from './nodeDetailConstants'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

const LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARN', 'WARNING', 'ERROR']

function computeDuration(job: DataModelingJob): string {
    if (!job.created_at || !job.last_run_at) {
        return '-'
    }
    const start = new Date(job.created_at).getTime()
    const end = new Date(job.last_run_at).getTime()
    const durationSeconds = (end - start) / 1000
    if (durationSeconds <= 0) {
        return '-'
    }
    return humanFriendlyDuration(durationSeconds)
}

export function NodeDetailMaterialization({ id }: { id: string }): JSX.Element | null {
    const { materializationJobs, materializationJobsLoading, jobsOffset, savedQuery } = useValues(
        nodeDetailSceneLogic({ id })
    )
    const { setJobsOffset } = useActions(nodeDetailSceneLogic({ id }))
    const { timezone } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const showDebugLogs = user?.is_staff || user?.is_impersonated

    if (!materializationJobs && !materializationJobsLoading) {
        return null
    }

    const jobs = materializationJobs?.results ?? []

    return (
        <div className="space-y-2 mt-4">
            <h3 className="text-lg font-semibold">Materialization history</h3>
            <LemonTable
                dataSource={jobs}
                loading={materializationJobsLoading}
                columns={[
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, job: DataModelingJob) => (
                            <LemonTag type={STATUS_TAG_SETTINGS[job.status] || 'default'}>{job.status}</LemonTag>
                        ),
                    },
                    {
                        title: 'Started at',
                        key: 'created_at',
                        render: (_, job: DataModelingJob) => (job.created_at ? <TZLabel time={job.created_at} /> : '-'),
                    },
                    {
                        title: 'Duration',
                        key: 'duration',
                        render: (_, job: DataModelingJob) => computeDuration(job),
                    },
                    {
                        title: 'Rows',
                        key: 'rows_materialized',
                        render: (_, job: DataModelingJob) =>
                            job.rows_materialized > 0 ? job.rows_materialized.toLocaleString() : '-',
                    },
                    {
                        title: 'Error',
                        key: 'error',
                        render: (_, job: DataModelingJob) =>
                            job.error ? (
                                <Tooltip title={job.error}>
                                    <span className="text-danger truncate max-w-xs inline-block">
                                        {job.error.slice(0, 80)}
                                        {job.error.length > 80 ? '...' : ''}
                                    </span>
                                </Tooltip>
                            ) : (
                                '-'
                            ),
                    },
                ]}
                expandable={
                    jobs.length > 0 && savedQuery
                        ? {
                              expandedRowRender: (job: DataModelingJob) => (
                                  <div className="p-4">
                                      <LogsViewer
                                          logicKey={`data_modeling_run:${job.id}`}
                                          sourceType="data_modeling_run"
                                          sourceId={savedQuery.id}
                                          groupByInstanceId={false}
                                          hideDateFilter
                                          hideLevelsFilter
                                          hideInstanceIdColumn
                                          defaultFilters={{
                                              instanceId: job.workflow_run_id,
                                              dateFrom: dayjsUtcToTimezone(job.created_at, timezone).format(
                                                  'YYYY-MM-DD HH:mm:ss'
                                              ),
                                              dateTo: job.last_run_at
                                                  ? dayjsUtcToTimezone(job.last_run_at, timezone)
                                                        .add(1, 'hour')
                                                        .format('YYYY-MM-DD HH:mm:ss')
                                                  : undefined,
                                              levels: showDebugLogs ? ['DEBUG', ...LOG_LEVELS] : LOG_LEVELS,
                                          }}
                                      />
                                  </div>
                              ),
                              rowExpandable: () => true,
                              noIndent: true,
                          }
                        : undefined
                }
            />
            {(materializationJobs?.next || materializationJobs?.previous) && (
                <div className="flex gap-2 justify-end">
                    {materializationJobs.previous && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => setJobsOffset(Math.max(0, jobsOffset - 10))}
                        >
                            Previous
                        </LemonButton>
                    )}
                    {materializationJobs.next && (
                        <LemonButton type="secondary" size="small" onClick={() => setJobsOffset(jobsOffset + 10)}>
                            Next
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )
}
