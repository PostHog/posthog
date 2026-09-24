import posthog from 'posthog-js'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { INSIGHT_TYPE_OPTIONS } from 'scenes/saved-insights/SavedInsights'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

export function SavedInsightsTypeFilter({
    insightType,
    setFilters,
    borderless,
}: {
    insightType: string
    setFilters: (filters: Partial<SavedInsightFilters>) => void
    borderless: boolean
}): JSX.Element {
    const active = !!insightType && insightType !== 'All types'
    return (
        <LemonSelect
            dropdownMatchSelectWidth={false}
            size="small"
            active={active}
            status={borderless && !active ? 'alt' : 'default'}
            onChange={(value) => {
                setFilters({ insightType: value as string })
                posthog.capture('saved insights filtered', { filter_type: 'insight_type', value })
            }}
            options={INSIGHT_TYPE_OPTIONS}
            value={insightType || 'All types'}
        />
    )
}
