import React from 'react'

import { IconClock, IconFilter, IconList, IconSort } from '@posthog/icons'

import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { pluralize } from 'lib/utils'
import { humanFriendlyDurationFilter } from 'scenes/session-recordings/filters/DurationFilter'

import { DurationType, RecordingUniversalFilters } from '~/types'

import { CompactUniversalFiltersDisplay } from './CompactUniversalFiltersDisplay'
import { DateRangeSummary, InsightDetailSectionDisplay } from './InsightDetails'

function DurationSummary({ filters }: { filters: RecordingUniversalFilters }): JSX.Element | null {
    if (!filters.duration || filters.duration.length === 0) {
        return null
    }

    return (
        <InsightDetailSectionDisplay icon={<IconClock />} label="Duration">
            {filters.duration.map((durationFilter, index) => (
                <React.Fragment key={index}>
                    <span className="font-medium">
                        {humanFriendlyDurationFilter(durationFilter, durationFilter.key as DurationType)}
                    </span>
                    {index < filters.duration.length - 1 && ' and '}
                </React.Fragment>
            ))}
        </InsightDetailSectionDisplay>
    )
}

function FiltersSummary({ filters }: { filters: RecordingUniversalFilters }): JSX.Element | null {
    const hasFilters = !!filters.filter_group?.values?.length

    if (!hasFilters && !filters.filter_test_accounts) {
        return null
    }

    return (
        <InsightDetailSectionDisplay icon={<IconFilter />} label="Filters">
            <CompactUniversalFiltersDisplay groupFilter={filters.filter_group} />
            {filters.filter_test_accounts && (
                <div>
                    <LemonTag size="small">Test accounts excluded</LemonTag>
                </div>
            )}
        </InsightDetailSectionDisplay>
    )
}

const ORDERABLE_FIELD_LABELS: Record<string, string> = {
    start_time: 'Start time',
    console_error_count: 'Console errors',
    click_count: 'Clicks',
    keypress_count: 'Key presses',
    mouse_activity_count: 'Mouse activity',
    activity_score: 'Activity score',
    recording_ttl: 'Recording TTL',
}

function OrderingSummary({ filters }: { filters: RecordingUniversalFilters }): JSX.Element | null {
    if (!filters.order && !filters.order_direction) {
        return null
    }

    const orderLabel = filters.order ? ORDERABLE_FIELD_LABELS[filters.order] || filters.order : 'Start time'
    const direction = filters.order_direction === 'ASC' ? 'ascending' : 'descending'

    return (
        <InsightDetailSectionDisplay icon={<IconSort />} label="Sort order">
            <div className="font-medium">
                {orderLabel} ({direction})
            </div>
        </InsightDetailSectionDisplay>
    )
}

function LimitSummary({ filters }: { filters: RecordingUniversalFilters }): JSX.Element | null {
    if (!filters.limit) {
        return null
    }

    return (
        <InsightDetailSectionDisplay icon={<IconList />} label="Limit">
            <div className="font-medium">{pluralize(filters.limit, 'recording')}</div>
        </InsightDetailSectionDisplay>
    )
}

export function RecordingsUniversalFiltersDisplay({
    filters,
    className,
}: {
    filters: RecordingUniversalFilters
    className?: string
}): JSX.Element {
    return (
        <div className={className ?? 'p-2 space-y-1.5'}>
            <DateRangeSummary dateFrom={filters.date_from} dateTo={filters.date_to} />
            <DurationSummary filters={filters} />
            <FiltersSummary filters={filters} />
            <OrderingSummary filters={filters} />
            <LimitSummary filters={filters} />
        </div>
    )
}
