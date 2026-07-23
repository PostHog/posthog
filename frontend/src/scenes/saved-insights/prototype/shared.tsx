/**
 * PROTOTYPE — THROWAWAY CODE. Small helpers shared by the saved-insights filtering variants.
 * See SavedInsightsPrototype.tsx for the plan.
 */
import { useValues } from 'kea'

import { isNonEmptyObject } from 'lib/utils/guards'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'

import { isNodeWithSource } from '~/queries/utils'
import { InsightType, SavedInsightsTabs } from '~/types'

import { INSIGHT_TYPES_METADATA, InsightTypeMetadata, QUERY_TYPES_METADATA } from '../insightTypesMetadata'
import { SavedInsightFilters, SavedInsightListItem, savedInsightsLogic } from '../savedInsightsLogic'

/** Insight types worth offering as filters, in menu order. */
export const PROTOTYPE_TYPE_OPTIONS: { value: InsightType; label: string; Icon: InsightTypeMetadata['icon'] }[] =
    Object.entries(INSIGHT_TYPES_METADATA)
        .filter(([, meta]) => meta.inMenu)
        .map(([value, meta]) => ({ value: value as InsightType, label: meta.name, Icon: meta.icon }))

export function insightTypeMetadata(insight: SavedInsightListItem): InsightTypeMetadata | null {
    if (!isNonEmptyObject(insight.query)) {
        return null
    }
    const kind = isNodeWithSource(insight.query) ? insight.query.source.kind : insight.query.kind
    return QUERY_TYPES_METADATA[kind] ?? null
}

export function PrototypeTypeIcon({
    insight,
    className,
}: {
    insight: SavedInsightListItem
    className?: string
}): JSX.Element | null {
    const meta = insightTypeMetadata(insight)
    return meta?.icon ? <meta.icon className={className} /> : null
}

export function PrototypeEmptyState(): JSX.Element {
    const { filters, usingFilters } = useValues(savedInsightsLogic)
    return (
        <div className="py-8">
            <SavedInsightsEmptyState filters={filters} usingFilters={usingFilters} />
        </div>
    )
}

/** Everything back to defaults (search included). */
export const CLEARED_FILTERS: Partial<SavedInsightFilters> = {
    search: '',
    tab: SavedInsightsTabs.All,
    insightType: 'All types',
    createdBy: 'All users',
    tags: undefined,
    favorited: false,
    hideFeatureFlagInsights: false,
}
