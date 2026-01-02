import { IconFilter, IconList, IconSort } from '@posthog/icons'

import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { pluralize } from 'lib/utils'

import { MaxErrorTrackingSearchResponse } from '~/queries/schema/schema-assistant-error-tracking'

import { DateRangeSummary, InsightDetailSectionDisplay } from './InsightDetails'

const ORDERABLE_FIELD_LABELS: Record<string, string> = {
    last_seen: 'Last seen',
    first_seen: 'First seen',
    occurrences: 'Occurrences',
    users: 'Users',
    sessions: 'Sessions',
    revenue: 'Revenue',
}

function StatusSummary({ filters }: { filters: MaxErrorTrackingSearchResponse }): JSX.Element | null {
    if (!filters.status) {
        return null
    }

    const statusLabel = filters.status === 'all' ? 'All statuses' : filters.status

    return (
        <InsightDetailSectionDisplay icon={<IconFilter />} label="Status">
            <div className="font-medium capitalize">{statusLabel}</div>
        </InsightDetailSectionDisplay>
    )
}

function SearchQuerySummary({ filters }: { filters: MaxErrorTrackingSearchResponse }): JSX.Element | null {
    if (!filters.search_query) {
        return null
    }

    return (
        <InsightDetailSectionDisplay icon={<IconFilter />} label="Search">
            <div className="font-medium">"{filters.search_query}"</div>
        </InsightDetailSectionDisplay>
    )
}

function OrderingSummary({ filters }: { filters: MaxErrorTrackingSearchResponse }): JSX.Element | null {
    if (!filters.order_by) {
        return null
    }

    const orderLabel = ORDERABLE_FIELD_LABELS[filters.order_by] || filters.order_by
    const direction = filters.order_direction === 'ASC' ? 'ascending' : 'descending'

    return (
        <InsightDetailSectionDisplay icon={<IconSort />} label="Sort order">
            <div className="font-medium">
                {orderLabel} ({direction})
            </div>
        </InsightDetailSectionDisplay>
    )
}

function LimitSummary({ filters }: { filters: MaxErrorTrackingSearchResponse }): JSX.Element | null {
    if (!filters.limit) {
        return null
    }

    return (
        <InsightDetailSectionDisplay icon={<IconList />} label="Limit">
            <div className="font-medium">{pluralize(filters.limit, 'issue')}</div>
        </InsightDetailSectionDisplay>
    )
}

function IssueCountSummary({ filters }: { filters: MaxErrorTrackingSearchResponse }): JSX.Element | null {
    const issueCount = filters.issues?.length ?? 0
    if (issueCount === 0) {
        return null
    }

    return (
        <div className="flex items-center gap-2">
            <LemonTag size="small" type="highlight">
                {issueCount} {pluralize(issueCount, 'issue', 'issues', false)} found
                {filters.has_more && ' (more available)'}
            </LemonTag>
        </div>
    )
}

export function ErrorTrackingUniversalFiltersDisplay({
    filters,
}: {
    filters: MaxErrorTrackingSearchResponse
}): JSX.Element {
    return (
        <div className="px-3 py-2 space-y-2">
            <DateRangeSummary dateFrom={filters.date_from} dateTo={filters.date_to} />
            <StatusSummary filters={filters} />
            <SearchQuerySummary filters={filters} />
            <OrderingSummary filters={filters} />
            <LimitSummary filters={filters} />
            <IssueCountSummary filters={filters} />
        </div>
    )
}
