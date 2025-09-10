import { useValues } from 'kea'

import { SkeletonLog } from 'lib/components/ActivityLog/ActivityLog'
import { describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { humanize } from 'lib/components/ActivityLog/humanizeActivity'
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
    <div className="text-center py-12">
        <div className="text-muted text-lg mb-2">No activity logs found</div>
        <p className="text-sm text-muted">Try adjusting your filters or date range to see more results.</p>
    </div>
)
