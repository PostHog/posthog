import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ExternalDataJob } from '~/types'

import { dataWarehouseSourceSettingsLogic } from './dataWarehouseSourceSettingsLogic'
import { LogsView } from './Logs'

const StatusTagSetting: Record<ExternalDataJob['status'], LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Failed: 'danger',
    Cancelled: 'default',
}

interface SyncsProps {
    id: string
}

export const Syncs = ({ id }: SyncsProps): JSX.Element => {
    const { jobs, jobsLoading, canLoadMoreJobs } = useValues(dataWarehouseSourceSettingsLogic({ id }))
    const { loadMoreJobs } = useActions(dataWarehouseSourceSettingsLogic({ id }))

    return (
        <LemonTable
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
                        return <LemonTag type={StatusTagSetting[job.status]}>{job.status}</LemonTag>
                    },
                },
                {
                    title: 'Rows synced',
                    render: (_, job) => {
                        return job.rows_synced
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
                    type="secondary"
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
