import { useValues } from 'kea'

import { SkeletonLog } from 'lib/components/ActivityLog/ActivityLog'
import { describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { DetectiveHog } from 'lib/components/hedgehogs'

import { AuditLogTable } from './AuditLogTable'
import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'

export function AdvancedActivityLogsList(): JSX.Element {
    const { advancedActivityLogs, advancedActivityLogsLoading, pagination } = useValues(advancedActivityLogsLogic)

    const humanizedLogs = advancedActivityLogs?.results ? humanize(advancedActivityLogs.results, describerFor) : []

    if (advancedActivityLogsLoading) {
        return <AdvancedActivityLogsListSkeleton />
    }

    if (!humanizedLogs.length) {
        return <AdvancedActivityLogsEmptyState />
    }

    return <AuditLogTable logItems={humanizedLogs} pagination={pagination} />
}

const AdvancedActivityLogsListSkeleton = (): JSX.Element => (
    <div className="space-y-4">
        <SkeletonLog />
        <SkeletonLog />
        <SkeletonLog />
        <SkeletonLog />
        <SkeletonLog />
    </div>
)

const AdvancedActivityLogsEmptyState = (): JSX.Element => (
    <div
        data-attr="billing-empty-state"
        className="flex flex-col border rounded px-4 py-8 items-center text-center mx-auto"
    >
        <DetectiveHog width="100" height="100" className="mb-4" />
        <h2 className="text-xl leading-tight">We couldn't find any activity logs for your current query.</h2>
        <p className="text-sm text-balance text-tertiary">
            Try adjusting your filters or date range to see more results.
        </p>
    </div>
)
