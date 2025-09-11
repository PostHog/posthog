import { useValues } from 'kea'

import { SkeletonLog } from 'lib/components/ActivityLog/ActivityLog'
import { describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { WarningHog } from 'lib/components/hedgehogs'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'

import { AuditLogTableHeader, AuditLogTableRow } from './AuditLogTable'
import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'

export function AdvancedActivityLogsList(): JSX.Element {
    const { advancedActivityLogs, advancedActivityLogsLoading, pagination } = useValues(advancedActivityLogsLogic)

    const humanizedLogs = advancedActivityLogs?.results ? humanize(advancedActivityLogs.results, describerFor) : []
    const paginationState = usePagination(humanizedLogs, pagination)

    if (advancedActivityLogsLoading) {
        return <AdvancedActivityLogsListSkeleton />
    }

    if (!humanizedLogs.length) {
        return <AdvancedActivityLogsEmptyState />
    }

    return (
        <div>
            <div className="border border-border rounded-md bg-bg-light overflow-hidden">
                <AuditLogTableHeader />
                <div className="divide-y divide-border">
                    {humanizedLogs.map((logItem, index) => (
                        <AuditLogTableRow key={index} logItem={logItem} />
                    ))}
                </div>
            </div>

            <div className="flex justify-center mt-6">
                <PaginationControl {...paginationState} data-attr="audit-logs-pagination" />
            </div>
        </div>
    )
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
        className="flex flex-col bg-white border rounded px-4 py-8 items-center text-center mx-auto"
    >
        <WarningHog width="100" height="100" className="mb-4" />
        <h2 className="text-xl leading-tight">We couldn't find any activity logs for your current query.</h2>
        <p className="text-sm text-balance text-tertiary">
            Try adjusting your filters or date range to see more results.
        </p>
    </div>
)
