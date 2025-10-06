import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ExternalDataJob, ExternalDataJobStatus, LogEntryLevel } from '~/types'

import { dataWarehouseSourceSettingsLogic } from './dataWarehouseSourceSettingsLogic'

const StatusTagSetting: Record<ExternalDataJob['status'], LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Failed: 'danger',
    [ExternalDataJobStatus.BillingLimits]: 'danger',
    [ExternalDataJobStatus.BillingLimitTooLow]: 'danger',
}

interface SyncsProps {
    id: string
}

const LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARN', 'WARNING', 'ERROR']

export const Syncs = ({ id }: SyncsProps): JSX.Element => {
    const { timezone } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { jobs, jobsLoading, canLoadMoreJobs } = useValues(
        dataWarehouseSourceSettingsLogic({ id, availableSources: {} })
    )
    const { loadMoreJobs } = useActions(dataWarehouseSourceSettingsLogic({ id, availableSources: {} }))
    const showDebugLogs = user?.is_staff || user?.is_impersonated

    return (
        <LemonTable
            hideScrollbar
            dataSource={jobs}
            loading={jobsLoading}
            disableTableWhileLoading={false}
            columns={[
                {
                    title: 'Schema',
                    render: (_, job) => {
                        return job.schema.name
                    },
                },
                {
                    title: 'Status',
                    render: (_, job) => {
                        const tagContent = (
                            <LemonTag type={StatusTagSetting[job.status] || 'default'}>{job.status}</LemonTag>
                        )
                        return job.latest_error && job.status === ExternalDataJobStatus.Failed ? (
                            <Tooltip title={job.latest_error}>{tagContent}</Tooltip>
                        ) : (
                            tagContent
                        )
                    },
                },
                {
                    title: 'Rows synced',
                    render: (_, job) => {
                        return job.rows_synced.toLocaleString()
                    },
                },
                {
                    title: 'Synced at',
                    render: (_, job) => {
                        return <TZLabel time={job.created_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                    },
                },
            ]}
            expandable={
                jobs.length > 0
                    ? {
                          expandedRowRender: (job) => (
                              <div className="p-4">
                                  <LogsViewer
                                      sourceType="external_data_jobs"
                                      sourceId={job.schema.id}
                                      groupByInstanceId={false}
                                      hideDateFilter={true}
                                      hideLevelsFilter={true}
                                      hideInstanceIdColumn={true}
                                      defaultFilters={{
                                          instanceId: job.workflow_run_id,
                                          dateFrom: dayjsUtcToTimezone(job.created_at, timezone)
                                              .add(-1, 'day')
                                              .toISOString(),
                                          dateTo: job.finished_at
                                              ? dayjsUtcToTimezone(job.finished_at, timezone)
                                                    .add(1, 'day')
                                                    .toISOString()
                                              : dayjs().add(1, 'day').toISOString(),
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
            footer={
                <LemonButton
                    onClick={loadMoreJobs}
                    type="tertiary"
                    fullWidth
                    center
                    disabledReason={!canLoadMoreJobs ? "There's nothing more to load" : undefined}
                >
                    {canLoadMoreJobs ? `Load older jobs` : 'No older jobs'}
                </LemonButton>
            }
        />
    )
}
