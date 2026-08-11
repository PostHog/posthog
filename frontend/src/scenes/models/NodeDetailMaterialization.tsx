import { useActions, useValues } from 'kea'

import { LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { computeJobDuration, jobLogsWindow } from 'scenes/data-warehouse/saved_queries/materializationJobUtils'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { DataModelingJob, LogEntryLevel } from '~/types'

import { STATUS_TAG_SETTINGS } from './nodeDetailConstants'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

const LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARN', 'WARNING', 'ERROR']

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
                pagination={{
                    controlled: true,
                    pageSize: 10,
                    currentPage: Math.floor(jobsOffset / 10) + 1,
                    entryCount: materializationJobs?.count,
                    onForward: () => setJobsOffset(jobsOffset + 10),
                    onBackward: () => setJobsOffset(Math.max(0, jobsOffset - 10)),
                }}
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
                        render: (_, job: DataModelingJob) => computeJobDuration(job),
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
                                              instanceId: job.workflow_run_id ?? undefined,
                                              ...jobLogsWindow(job, timezone),
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
        </div>
    )
}
