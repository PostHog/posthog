import { BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'

import { ConversionGoalFilter, MarketingAnalyticsAttributionBreakdown, NodeKind } from '~/queries/schema/schema-general'

/**
 * Shared by every marketing surface that slices sessions by a dimension. Lives apart from either
 * explorer's logic so the retention tab doesn't have to import the attribution tab to render a label.
 */
export const BREAKDOWN_LABELS: Record<MarketingAnalyticsAttributionBreakdown, string> = {
    [MarketingAnalyticsAttributionBreakdown.Channel]: 'Channel',
    [MarketingAnalyticsAttributionBreakdown.Source]: 'Source',
    [MarketingAnalyticsAttributionBreakdown.Campaign]: 'Campaign',
    [MarketingAnalyticsAttributionBreakdown.Medium]: 'Medium',
    [MarketingAnalyticsAttributionBreakdown.Content]: 'Content',
    [MarketingAnalyticsAttributionBreakdown.Term]: 'Term',
    [MarketingAnalyticsAttributionBreakdown.ReferringDomain]: 'Referring domain',
    [MarketingAnalyticsAttributionBreakdown.LandingPage]: 'Landing page',
}

/** True for the row the backend folds the long tail of breakdown values into. */
export const isFoldedBreakdownValue = (value: string): boolean => value === BREAKDOWN_OTHER_STRING_LABEL

/**
 * What a breakdown value reads as. The folded row arrives as a sentinel string, and a value can be
 * empty when the session carried nothing for this dimension — neither is something to show a marketer.
 */
export const displayBreakdownValue = (value: string, dimensionLabel: string): string => {
    if (isFoldedBreakdownValue(value)) {
        return 'Other'
    }
    return value || `(no ${dimensionLabel.toLowerCase()})`
}

/**
 * Goals these explorers can count. Data warehouse goals are excluded: their conversions live in a
 * warehouse table keyed by distinct id, so the events-based session queries have nothing to join them on.
 */
export const attributableConversionGoals = (conversionGoals: ConversionGoalFilter[]): ConversionGoalFilter[] =>
    (conversionGoals || []).filter((goal) => goal.kind !== NodeKind.DataWarehouseNode)
