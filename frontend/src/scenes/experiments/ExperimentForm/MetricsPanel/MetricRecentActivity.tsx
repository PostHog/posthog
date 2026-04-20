import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import type { ExperimentMetric } from '~/queries/schema/schema-general'

import { metricRecentActivityLogic } from './metricRecentActivityLogic'

export type MetricRecentActivityProps = {
    metric: ExperimentMetric
    filterTestAccounts: boolean
}

export const MetricRecentActivity = ({ metric, filterTestAccounts }: MetricRecentActivityProps): JSX.Element => {
    const { eventCount, eventCountLoading } = useValues(metricRecentActivityLogic({ metric, filterTestAccounts }))

    if (eventCountLoading) {
        return (
            <div className="text-xs text-muted">
                <Spinner className="mr-1" />
                Loading...
            </div>
        )
    }

    const count = eventCount ?? 0

    return (
        <div className="flex flex-col gap-1">
            <span className="text-muted">events in the past 14 days</span>
            <span className="text-2xl font-semibold text-right">{count.toLocaleString()}</span>
        </div>
    )
}
