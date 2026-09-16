import { BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'

import {
    ConversionGoalFilter,
    MarketingAnalyticsAttributionBreakdown,
    NodeKind,
    WebStatsBreakdown,
} from '~/queries/schema/schema-general'

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

/** The dimensions the dashboard offers. Content and term are left out because a marketer rarely
 * breaks a whole dashboard down by them, and every extra option costs a row in the picker. */
export const DASHBOARD_BREAKDOWNS: readonly MarketingAnalyticsAttributionBreakdown[] = [
    MarketingAnalyticsAttributionBreakdown.Channel,
    MarketingAnalyticsAttributionBreakdown.Source,
    MarketingAnalyticsAttributionBreakdown.Campaign,
    MarketingAnalyticsAttributionBreakdown.Medium,
    MarketingAnalyticsAttributionBreakdown.ReferringDomain,
    MarketingAnalyticsAttributionBreakdown.LandingPage,
]

export const DEFAULT_DASHBOARD_BREAKDOWN = MarketingAnalyticsAttributionBreakdown.Channel

/** One page-level breakdown drives both the retention query, which takes this enum, and the web
 * stats tables, which take their own. Declared total so a new member fails to compile here rather
 * than silently dropping a table. */
export const ATTRIBUTION_BREAKDOWN_TO_WEB_STATS: Record<MarketingAnalyticsAttributionBreakdown, WebStatsBreakdown> = {
    [MarketingAnalyticsAttributionBreakdown.Channel]: WebStatsBreakdown.InitialChannelType,
    [MarketingAnalyticsAttributionBreakdown.Source]: WebStatsBreakdown.InitialUTMSource,
    [MarketingAnalyticsAttributionBreakdown.Campaign]: WebStatsBreakdown.InitialUTMCampaign,
    [MarketingAnalyticsAttributionBreakdown.Medium]: WebStatsBreakdown.InitialUTMMedium,
    [MarketingAnalyticsAttributionBreakdown.Content]: WebStatsBreakdown.InitialUTMContent,
    [MarketingAnalyticsAttributionBreakdown.Term]: WebStatsBreakdown.InitialUTMTerm,
    [MarketingAnalyticsAttributionBreakdown.ReferringDomain]: WebStatsBreakdown.InitialReferringDomain,
    [MarketingAnalyticsAttributionBreakdown.LandingPage]: WebStatsBreakdown.InitialPage,
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
