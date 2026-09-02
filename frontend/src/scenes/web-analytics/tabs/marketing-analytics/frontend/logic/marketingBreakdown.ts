import { BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'

import { ConversionGoalFilter, MarketingAnalyticsAttributionBreakdown, NodeKind } from '~/queries/schema/schema-general'

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

/** Neither the folded sentinel nor an empty value is something to show a marketer raw. */
export const displayBreakdownValue = (value: string, dimensionLabel: string): string => {
    if (isFoldedBreakdownValue(value)) {
        return 'Other'
    }
    return value || `(no ${dimensionLabel.toLowerCase()})`
}

/** Warehouse goals are keyed by distinct id, so the events-based session queries can't join them. */
export const attributableConversionGoals = (conversionGoals: ConversionGoalFilter[]): ConversionGoalFilter[] =>
    (conversionGoals || []).filter((goal) => goal.kind !== NodeKind.DataWarehouseNode)
