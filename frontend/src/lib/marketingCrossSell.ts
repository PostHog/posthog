import posthog from 'posthog-js'

import { uuid } from 'lib/utils/dom'

import { WebStatsBreakdown } from '~/queries/schema/schema-general'

const STORAGE_KEY = 'web-analytics-marketing-cross-sell'
const ATTRIBUTION_WINDOW_MS = 24 * 60 * 60 * 1000
const CROSS_SELL_PROPERTIES = {
    cross_sell_from: 'web_analytics',
    cross_sell_to: 'marketing_analytics',
    cross_sell_placement: 'sources_table',
    cross_sell_variant: 'contextual_card',
    cross_sell_attribution_model: 'first_ad_source_after_last_click_24h_same_tab',
}

export interface MarketingCrossSellAttribution {
    cross_sell_id: string
    cross_sell_clicked_at: number
    breakdown: WebStatsBreakdown
    has_connected_sources: boolean
    team_id: number
    distinct_id: string
}

export function supportsMarketingCrossSell(breakdown: WebStatsBreakdown): boolean {
    return [
        WebStatsBreakdown.InitialChannelType,
        WebStatsBreakdown.InitialUTMSource,
        WebStatsBreakdown.InitialUTMMedium,
        WebStatsBreakdown.InitialUTMCampaign,
        WebStatsBreakdown.InitialUTMContent,
        WebStatsBreakdown.InitialUTMTerm,
        WebStatsBreakdown.InitialUTMSourceMediumCampaign,
    ].includes(breakdown)
}

export function captureMarketingCrossSellClick(
    teamId: number,
    breakdown: WebStatsBreakdown,
    hasConnectedSources: boolean
): void {
    const attribution: MarketingCrossSellAttribution = {
        cross_sell_id: uuid(),
        cross_sell_clicked_at: Date.now(),
        breakdown,
        has_connected_sources: hasConnectedSources,
        team_id: teamId,
        distinct_id: posthog.get_distinct_id(),
    }
    try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(attribution))
    } catch {
        // Storage restrictions must not prevent navigation to Marketing analytics.
    }
    const { distinct_id: _, ...properties } = attribution
    posthog.capture('web analytics marketing cross sell clicked', { ...CROSS_SELL_PROPERTIES, ...properties })
}

export function getMarketingCrossSellAttribution(teamId: number): MarketingCrossSellAttribution | null {
    try {
        const saved: Partial<MarketingCrossSellAttribution> = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null')
        if (
            !saved ||
            saved.team_id !== teamId ||
            saved.distinct_id !== posthog.get_distinct_id() ||
            typeof saved.cross_sell_id !== 'string' ||
            typeof saved.cross_sell_clicked_at !== 'number' ||
            typeof saved.has_connected_sources !== 'boolean' ||
            !saved.breakdown ||
            !supportsMarketingCrossSell(saved.breakdown) ||
            Date.now() < saved.cross_sell_clicked_at ||
            Date.now() - saved.cross_sell_clicked_at > ATTRIBUTION_WINDOW_MS
        ) {
            return null
        }
        return {
            cross_sell_id: saved.cross_sell_id,
            cross_sell_clicked_at: saved.cross_sell_clicked_at,
            breakdown: saved.breakdown,
            has_connected_sources: saved.has_connected_sources,
            team_id: teamId,
            distinct_id: saved.distinct_id,
        }
    } catch {
        return null
    }
}

export function captureMarketingCrossSellSourceCreated(
    attribution: MarketingCrossSellAttribution,
    sourceId: string,
    sourceType: string
): void {
    const current = getMarketingCrossSellAttribution(attribution.team_id)
    if (current?.cross_sell_id !== attribution.cross_sell_id) {
        return
    }
    try {
        sessionStorage.removeItem(STORAGE_KEY)
    } catch {
        // A successful source connection must not depend on browser storage.
    }
    const { distinct_id: _, ...properties } = attribution
    posthog.capture('web analytics marketing cross sell source created', {
        ...CROSS_SELL_PROPERTIES,
        ...properties,
        source_id: sourceId,
        source_type: sourceType,
    })
}
