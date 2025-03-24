import { LemonButton, LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'

import { ExternalDataJob, ExternalDataJobStatus } from '~/types'

import { dataWarehouseSourceSettingsLogic } from './dataWarehouseSourceSettingsLogic'
import { LogsView } from './Logs'

const StatusTagSetting: Record<ExternalDataJob['status'], LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Failed: 'danger',
    'Billing limits': 'danger',
}

interface SyncsProps {
    id: string
}

export const Syncs = ({ id }: SyncsProps): JSX.Element => {
    const { jobs, jobsLoading, canLoadMoreJobs } = useValues(dataWarehouseSourceSettingsLogic({ id }))
    const { loadMoreJobs } = useActions(dataWarehouseSourceSettingsLogic({ id }))

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
                                  <LogsView job={job} />
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
