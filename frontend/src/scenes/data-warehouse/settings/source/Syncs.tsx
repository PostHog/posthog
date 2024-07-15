import { TZLabel } from '@posthog/apps-common'
import { LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { ExternalDataJob } from '~/types'

import { dataWarehouseSourceSettingsLogic } from './dataWarehouseSourceSettingsLogic'

const StatusTagSetting: Record<ExternalDataJob['status'], LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Failed: 'danger',
    Cancelled: 'default',
}

export const Syncs = (): JSX.Element => {
    const { jobs, jobsLoading } = useValues(dataWarehouseSourceSettingsLogic)

    return (
        <LemonTable
            dataSource={jobs}
            loading={jobsLoading}
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
        />
    )
}
