import { useActions, useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { AnalyticsListDisplayConfiguration } from '~/queries/schema/schema-general'

import { AnalyticsOrderBy } from './analyticsFeed'
import { analyticsListLogic } from './analyticsListLogic'

type AnalyticsSort = NonNullable<AnalyticsListDisplayConfiguration['default_sort']>

export const ANALYTICS_SORT_LABELS: Record<AnalyticsOrderBy, string> = {
    '-last_viewed_at': 'Last viewed by me',
    '-created_at': 'Created at',
    '-view_count': 'Views',
    '-viewer_count': 'Viewers',
    // Only a header click or a link reaches these orders, so each shows as an option only while it is in force.
    last_viewed_at: 'Last viewed by me, oldest first',
    created_at: 'Created at, oldest first',
}

const SORTS: AnalyticsSort[] = ['-last_viewed_at', '-created_at', '-view_count', '-viewer_count']

function isAnalyticsSort(orderBy: AnalyticsOrderBy): orderBy is AnalyticsSort {
    return (SORTS as AnalyticsOrderBy[]).includes(orderBy)
}

/** The list's order. A pick is saved on the person, so every Analytics list opens on it. */
export function AnalyticsSortSelect(): JSX.Element {
    const { filters, defaultSort } = useValues(analyticsListLogic)
    const { setDefaultSort } = useActions(analyticsListLogic)
    const sort = filters.orderBy ?? defaultSort
    const options: AnalyticsOrderBy[] = isAnalyticsSort(sort) ? SORTS : [...SORTS, sort]

    return (
        <Select<AnalyticsOrderBy>
            items={options.map((value) => ({ value, label: ANALYTICS_SORT_LABELS[value] }))}
            value={sort}
            onValueChange={(next) => {
                if (next && isAnalyticsSort(next)) {
                    setDefaultSort(next)
                }
            }}
        >
            <SelectTrigger size="sm" aria-label="Sort by" data-attr="analytics-list-sort">
                <span className="text-muted-foreground">Sort by</span>
                <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
                {options.map((value) => (
                    <SelectItem key={value} value={value} data-attr="analytics-list-default-sort">
                        {ANALYTICS_SORT_LABELS[value]}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
