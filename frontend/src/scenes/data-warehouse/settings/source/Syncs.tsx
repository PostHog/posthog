import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider, LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjsUtcToTimezone } from 'lib/dayjs'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
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
    const { jobs, jobsLoading, canLoadMoreJobs, selectedSchemas } = useValues(
        dataWarehouseSourceSettingsLogic({ id, availableSources: {} })
    )
    const { loadMoreJobs, setSelectedSchemas } = useActions(
        dataWarehouseSourceSettingsLogic({ id, availableSources: {} })
    )
    const showDebugLogs = user?.is_staff || user?.is_impersonated

    const schemaOptions = Array.from(new Set(jobs.map((job) => job.schema.name)))
        .sort()
        .map((schemaName) => ({
            key: schemaName,
            label: schemaName,
        }))

    const filteredJobs =
        selectedSchemas.length > 0 ? jobs.filter((job) => selectedSchemas.includes(job.schema.name)) : jobs

    return (
        <>
            {schemaOptions.length > 1 && (
                <>
                    <div className="flex items-center gap-2 mb-2">
                        <LemonLabel>Schema</LemonLabel>
                        <LemonInputSelect
                            mode="multiple"
                            bulkActions="select-and-clear-all"
                            displayMode="count"
                            size="small"
                            value={selectedSchemas}
                            onChange={setSelectedSchemas}
                            options={schemaOptions}
                            placeholder="All"
                            allowCustomValues={false}
                        />
                    </div>
                    <LemonDivider className="my-4" />
                </>
            )}
            <LemonTable
                hideScrollbar
                dataSource={filteredJobs}
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
                    filteredJobs.length > 0
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
                                              dateFrom: dayjsUtcToTimezone(job.created_at, timezone).format(
                                                  'YYYY-MM-DD HH:mm:ss'
                                              ),
                                              dateTo: job.finished_at
                                                  ? dayjsUtcToTimezone(job.finished_at, timezone)
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
        </>
    )
}
