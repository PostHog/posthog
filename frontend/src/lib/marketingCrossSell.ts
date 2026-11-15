import posthog from 'posthog-js'

import { uuid } from 'lib/utils/dom'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'

import {
    NativeMarketingSource,
    ProductIntentContext,
    ProductKey,
    WebStatsBreakdown,
} from '~/queries/schema/schema-general'

const STORAGE_KEY = 'web-analytics-marketing-cross-sell'
const SHOWN_STORAGE_KEY = 'web-analytics-marketing-cross-sell-shown'
const ATTRIBUTION_WINDOW_MS = 24 * 60 * 60 * 1000
const CROSS_SELL_PROPERTIES = {
    cross_sell_from: 'web_analytics',
    cross_sell_to: 'marketing_analytics',
    cross_sell_attribution_model: 'first_ad_source_after_last_click_24h_same_tab',
}

export type MarketingCrossSellPlacement = 'sources_table' | 'table_row' | 'filter_hint'
export type MarketingCrossSellVariant = 'contextual_card' | 'quantified_card' | 'row_action' | 'filter_hint'

const VARIANT_PLACEMENTS: Record<MarketingCrossSellVariant, MarketingCrossSellPlacement> = {
    contextual_card: 'sources_table',
    quantified_card: 'sources_table',
    row_action: 'table_row',
    filter_hint: 'filter_hint',
}

export interface MarketingCrossSellSurface {
    variant: MarketingCrossSellVariant
    platform?: NativeMarketingSource | null
}

const DEFAULT_SURFACE: MarketingCrossSellSurface = { variant: 'contextual_card' }

function surfaceProperties(surface: MarketingCrossSellSurface): {
    cross_sell_placement: MarketingCrossSellPlacement
    cross_sell_variant: MarketingCrossSellVariant
    platform: NativeMarketingSource | null
} {
    return {
        cross_sell_placement: VARIANT_PLACEMENTS[surface.variant],
        cross_sell_variant: surface.variant,
        platform: surface.platform ?? null,
    }
}

export interface MarketingCrossSellAttribution {
    cross_sell_id: string
    cross_sell_clicked_at: number
    cross_sell_placement: MarketingCrossSellPlacement
    cross_sell_variant: MarketingCrossSellVariant
    platform: NativeMarketingSource | null
    breakdown: WebStatsBreakdown | null
    has_connected_sources: boolean | null
    team_id: number
    distinct_id: string
}

export interface MarketingCrossSellShownProperties {
    teamId: number
    surface: MarketingCrossSellSurface
    hasConnectedSources: boolean | null
    paidVisitors?: number
    paidShare?: number
    platforms?: NativeMarketingSource[]
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

function markShownThisSession(sessionKey: string): boolean {
    try {
        if (sessionStorage.getItem(sessionKey)) {
            return false
        }
        sessionStorage.setItem(sessionKey, '1')
        return true
    } catch {
        return true
    }
}

export function captureMarketingCrossSellShown({
    teamId,
    surface,
    hasConnectedSources,
    paidVisitors,
    paidShare,
    platforms,
}: MarketingCrossSellShownProperties): void {
    const properties = surfaceProperties(surface)
    if (
        !markShownThisSession(
            `${SHOWN_STORAGE_KEY}:${teamId}:${properties.cross_sell_placement}:${properties.cross_sell_variant}`
        )
    ) {
        return
    }
    posthog.capture('web analytics marketing cross sell shown', {
        ...CROSS_SELL_PROPERTIES,
        ...properties,
        team_id: teamId,
        has_connected_sources: hasConnectedSources,
        paid_visitors: paidVisitors,
        paid_share: paidShare,
        platforms,
    })
}

export function captureMarketingCrossSellDismissed(
    teamId: number,
    surface: MarketingCrossSellSurface,
    dismissCount: number
): void {
    posthog.capture('web analytics marketing cross sell dismissed', {
        ...CROSS_SELL_PROPERTIES,
        ...surfaceProperties(surface),
        team_id: teamId,
        dismiss_count: dismissCount,
    })
}

export function captureMarketingCrossSellClick(
    teamId: number,
    breakdown: WebStatsBreakdown | null,
    hasConnectedSources: boolean | null,
    surface: MarketingCrossSellSurface = DEFAULT_SURFACE
): void {
    const attribution: MarketingCrossSellAttribution = {
        cross_sell_id: uuid(),
        cross_sell_clicked_at: Date.now(),
        ...surfaceProperties(surface),
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
    void addProductIntentForCrossSell({
        from: ProductKey.WEB_ANALYTICS,
        to: ProductKey.MARKETING_ANALYTICS,
        intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
        metadata: { placement: attribution.cross_sell_placement, variant: attribution.cross_sell_variant },
    }).catch(() => null)
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
            (saved.has_connected_sources !== null && typeof saved.has_connected_sources !== 'boolean') ||
            (saved.breakdown != null && !supportsMarketingCrossSell(saved.breakdown)) ||
            Date.now() < saved.cross_sell_clicked_at ||
            Date.now() - saved.cross_sell_clicked_at > ATTRIBUTION_WINDOW_MS
        ) {
            return null
        }
        return {
            cross_sell_id: saved.cross_sell_id,
            cross_sell_clicked_at: saved.cross_sell_clicked_at,
            cross_sell_placement: saved.cross_sell_placement ?? VARIANT_PLACEMENTS[DEFAULT_SURFACE.variant],
            cross_sell_variant: saved.cross_sell_variant ?? DEFAULT_SURFACE.variant,
            platform: saved.platform ?? null,
            breakdown: saved.breakdown ?? null,
            has_connected_sources: saved.has_connected_sources ?? null,
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
