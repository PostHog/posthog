import type { ErrorTrackingIssue } from '~/queries/schema/schema-general'

export type ErrorTrackingWidgetListResult = {
    results?: ErrorTrackingIssue[]
    hasMore?: boolean
    limit?: number
    totalCount?: number
    totalCountCapped?: boolean
}

export type WidgetIssueMetadataDelta = {
    status?: ErrorTrackingIssue['status']
    assignee?: ErrorTrackingIssue['assignee'] | null
}

export type WidgetIssueMetadataContext = {
    statusFilter: string
    assigneeFilter?: ErrorTrackingIssue['assignee'] | null
}

function issueAssigneeMatchesFilter(
    issueAssignee: ErrorTrackingIssue['assignee'] | null | undefined,
    assigneeFilter: ErrorTrackingIssue['assignee'] | null | undefined
): boolean {
    if (!assigneeFilter) {
        return true
    }
    if (!issueAssignee) {
        return false
    }
    return issueAssignee.type === assigneeFilter.type && issueAssignee.id === assigneeFilter.id
}

export function issueMatchesWidgetTileFilters(
    issue: Pick<ErrorTrackingIssue, 'status' | 'assignee'>,
    context: WidgetIssueMetadataContext
): boolean {
    if (context.statusFilter !== 'all' && issue.status !== context.statusFilter) {
        return false
    }
    return issueAssigneeMatchesFilter(issue.assignee, context.assigneeFilter)
}

export function applyIssueMetadataToWidgetListResult(
    result: ErrorTrackingWidgetListResult,
    issueId: string,
    delta: WidgetIssueMetadataDelta,
    context: WidgetIssueMetadataContext
): ErrorTrackingWidgetListResult {
    const results = result.results ?? []
    if (!results.some((issue) => issue.id === issueId)) {
        return result
    }

    const updated = results.map((issue) => (issue.id === issueId ? { ...issue, ...delta } : issue))

    const patchedIssue = updated.find((issue) => issue.id === issueId)
    const shouldRemoveFromFilteredList =
        patchedIssue !== undefined && !issueMatchesWidgetTileFilters(patchedIssue, context)

    return {
        ...result,
        results: shouldRemoveFromFilteredList ? updated.filter((issue) => issue.id !== issueId) : updated,
        totalCount:
            shouldRemoveFromFilteredList && result.totalCount !== undefined
                ? Math.max(0, result.totalCount - 1)
                : result.totalCount,
    }
}
