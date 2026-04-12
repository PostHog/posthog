import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import {
    MARKETING_INTEGRATION_CONFIGS,
    type MarketingAnalyticsConfig,
    VALID_NATIVE_MARKETING_SOURCES,
} from '~/queries/schema/schema-general'

import { similarityScore } from '../components/settings/stringSimilarity'
import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from './marketingAnalyticsTilesLogic'
import type { utmAuditLogicType } from './utmAuditLogicType'

export interface UtmIssue {
    field: string
    severity: 'error' | 'warning'
    message: string
}

export interface CampaignAuditResult {
    campaign_name: string
    campaign_id: string
    source_name: string
    spend: number
    clicks: number
    impressions: number
    has_utm_events: boolean
    event_count: number
    issues: UtmIssue[]
}

export type MatchType = 'none' | 'auto' | 'mapped'

export interface UtmEvent {
    utm_campaign: string
    utm_source: string
    event_count: number
    campaign_match: MatchType
    source_match: MatchType
    matched_campaign: string | null
}

export interface UtmAuditResponse {
    total_campaigns: number
    campaigns_with_issues: number
    campaigns_without_issues: number
    total_spend_at_risk: number
    results: CampaignAuditResult[]
    all_utm_events: UtmEvent[]
}

export interface KnownSource {
    source: string
    integration: string
}

export interface AggregatedUtmSource {
    utm_source: string
    event_count: number
    mapped: boolean
    match_type: MatchType
    integration: string | null
}

export type HealthTab = 'campaign' | 'source' | 'settings'

// Build known sources from integration configs
const KNOWN_SOURCES_LIST: KnownSource[] = VALID_NATIVE_MARKETING_SOURCES.flatMap((nativeSource) => {
    const config = MARKETING_INTEGRATION_CONFIGS[nativeSource]
    return config.defaultSources.map((s: string) => ({
        source: s,
        integration: nativeSource,
    }))
})

const KNOWN_SOURCES_SET = new Set(KNOWN_SOURCES_LIST.map((s) => s.source))

// Map source value -> integration name (e.g. "google" -> "GoogleAds", "adwords" -> "GoogleAds")
const SOURCE_TO_INTEGRATION_NAME: Record<string, string> = Object.fromEntries(
    KNOWN_SOURCES_LIST.map((s) => [s.source, s.integration])
)

export const utmAuditLogic = kea<utmAuditLogicType>([
    path(['scenes', 'webAnalytics', 'utmAuditLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId', 'baseCurrency'],
            marketingAnalyticsSettingsLogic,
            ['marketingAnalyticsConfig'],
        ],
        actions: [dataNodeCollectionLogic({ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }), ['reloadAll']],
    })),
    actions({
        setActiveTab: (tab: HealthTab) => ({ tab }),
        setSelectedCampaign: (campaignName: string | null) => ({ campaignName }),
        setSelectedUtmCampaign: (utmCampaign: string | null) => ({ utmCampaign }),
        setSourceFilter: (source: string | null) => ({ source }),
        setCampaignSearch: (search: string) => ({ search }),
        setUtmSearch: (search: string) => ({ search }),
    }),
    reducers({
        activeTab: [
            'campaign' as HealthTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        selectedCampaign: [
            null as string | null,
            {
                setSelectedCampaign: (current, { campaignName }) => (current === campaignName ? null : campaignName),
                setSourceFilter: () => null,
            },
        ],
        selectedUtmCampaign: [
            null as string | null,
            {
                setSelectedUtmCampaign: (current, { utmCampaign }) => (current === utmCampaign ? null : utmCampaign),
                setSourceFilter: () => null,
            },
        ],
        sourceFilter: [
            null as string | null,
            {
                setSourceFilter: (_, { source }) => source,
            },
        ],
        campaignSearch: [
            '',
            {
                setCampaignSearch: (_, { search }) => search,
            },
        ],
        utmSearch: [
            '',
            {
                setUtmSearch: (_, { search }) => search,
            },
        ],
        auditDataFailure: [
            null as string | null,
            {
                loadAuditData: () => null,
                loadAuditDataSuccess: () => null,
                loadAuditDataFailure: (_, { error }) => error,
            },
        ],
    }),
    loaders(({ values }) => ({
        auditData: [
            null as UtmAuditResponse | null,
            {
                loadAuditData: async () => {
                    const params: Record<string, string> = {
                        date_from: '-30d',
                    }
                    const response = await api.get(
                        `api/environments/${values.currentTeamId}/marketing_analytics/utm_audit`,
                        params
                    )
                    return response as UtmAuditResponse
                },
            },
        ],
    })),
    selectors({
        // Campaign tab — left panel
        availableSources: [
            (s) => [s.auditData],
            (auditData: UtmAuditResponse | null): string[] => {
                if (!auditData) {
                    return []
                }
                return [...new Set(auditData.results.map((r) => r.source_name))].sort()
            },
        ],
        filteredCampaigns: [
            (s) => [s.auditData, s.sourceFilter, s.campaignSearch],
            (
                auditData: UtmAuditResponse | null,
                sourceFilter: string | null,
                campaignSearch: string
            ): CampaignAuditResult[] => {
                if (!auditData) {
                    return []
                }
                let campaigns = auditData.results
                if (sourceFilter) {
                    campaigns = campaigns.filter((r) => r.source_name === sourceFilter)
                }
                const q = campaignSearch.toLowerCase().trim()
                if (q) {
                    campaigns = campaigns.filter(
                        (r) => r.campaign_name.toLowerCase().includes(q) || r.campaign_id.toLowerCase().includes(q)
                    )
                }
                return campaigns
            },
        ],
        campaignsWithoutUtmCount: [
            (s) => [s.auditData],
            (auditData: UtmAuditResponse | null): number => {
                if (!auditData) {
                    return 0
                }
                return auditData.results.filter((r) => r.event_count === 0).length
            },
        ],
        // Source stats for summary (unfiltered)
        totalUtmSourcesCount: [
            (s) => [s.auditData],
            (auditData: UtmAuditResponse | null): number => {
                if (!auditData) {
                    return 0
                }
                return new Set(auditData.all_utm_events.map((e) => e.utm_source)).size
            },
        ],
        unmappedSourcesCount: [
            (s) => [s.auditData, s.allMappedSources],
            (auditData: UtmAuditResponse | null, allMapped: Set<string>): number => {
                if (!auditData) {
                    return 0
                }
                const uniqueSources = new Set(auditData.all_utm_events.map((e) => e.utm_source))
                return [...uniqueSources].filter((s) => !allMapped.has(s)).length
            },
        ],

        // Selected campaign data (for Map button)
        selectedCampaignData: [
            (s) => [s.auditData, s.selectedCampaign],
            (auditData: UtmAuditResponse | null, selectedCampaign: string | null): CampaignAuditResult | null => {
                if (!auditData || !selectedCampaign) {
                    return null
                }
                return auditData.results.find((r) => r.campaign_name === selectedCampaign) ?? null
            },
        ],

        // Campaign tab — right panel
        sortedUtmCampaigns: [
            (s) => [s.auditData, s.selectedCampaign, s.utmSearch],
            (auditData: UtmAuditResponse | null, selectedCampaign: string | null, search: string): UtmEvent[] => {
                if (!auditData) {
                    return []
                }
                let events = auditData.all_utm_events
                const q = search.toLowerCase().trim()
                if (q) {
                    events = events.filter(
                        (e) => e.utm_campaign.toLowerCase().includes(q) || e.utm_source.toLowerCase().includes(q)
                    )
                }
                if (selectedCampaign) {
                    return [...events].sort(
                        (a, b) =>
                            similarityScore(selectedCampaign, b.utm_campaign) -
                            similarityScore(selectedCampaign, a.utm_campaign)
                    )
                }
                return events
            },
        ],

        // All mapped sources: defaults + team's custom source mappings
        allMappedSources: [
            (s) => [s.marketingAnalyticsConfig],
            (config: MarketingAnalyticsConfig | null): Set<string> => {
                const mapped = new Set(KNOWN_SOURCES_SET)
                const customMappings = config?.custom_source_mappings || {}
                for (const sources of Object.values(customMappings)) {
                    for (const source of sources) {
                        mapped.add(source.toLowerCase().trim())
                    }
                }
                return mapped
            },
        ],

        // Source tab — right panel
        aggregatedUtmSources: [
            (s) => [s.auditData, s.utmSearch, s.allMappedSources, s.marketingAnalyticsConfig],
            (
                auditData: UtmAuditResponse | null,
                search: string,
                allMappedSources: Set<string>,
                marketingConfig: MarketingAnalyticsConfig | null
            ): AggregatedUtmSource[] => {
                if (!auditData) {
                    return []
                }
                // Aggregate by utm_source
                const sourceMap = new Map<string, number>()
                for (const e of auditData.all_utm_events) {
                    sourceMap.set(e.utm_source, (sourceMap.get(e.utm_source) || 0) + e.event_count)
                }

                // Build custom source → integration map from team config
                const customSourceIntegration: Record<string, string> = {}
                if (marketingConfig?.custom_source_mappings) {
                    for (const [integration, sources_list] of Object.entries(marketingConfig.custom_source_mappings)) {
                        for (const s of sources_list) {
                            customSourceIntegration[s.toLowerCase().trim()] = integration
                        }
                    }
                }

                let sources: AggregatedUtmSource[] = Array.from(sourceMap.entries()).map(
                    ([utm_source, event_count]) => {
                        const isDefault = KNOWN_SOURCES_SET.has(utm_source)
                        const isCustom = !isDefault && allMappedSources.has(utm_source)
                        const integration = isDefault
                            ? SOURCE_TO_INTEGRATION_NAME[utm_source] || null
                            : isCustom
                              ? customSourceIntegration[utm_source] || null
                              : null
                        return {
                            utm_source,
                            event_count,
                            mapped: isDefault || isCustom,
                            match_type: isDefault
                                ? ('auto' as MatchType)
                                : isCustom
                                  ? ('mapped' as MatchType)
                                  : ('none' as MatchType),
                            integration,
                        }
                    }
                )

                const q = search.toLowerCase().trim()
                if (q) {
                    sources = sources.filter((s) => s.utm_source.toLowerCase().includes(q))
                }

                return [...sources].sort((a, b) => {
                    // Unmapped first, then by event count desc
                    if (a.mapped !== b.mapped) {
                        return a.mapped ? 1 : -1
                    }
                    return b.event_count - a.event_count
                })
            },
        ],
    }),
    listeners(({ actions }) => ({
        reloadAll: () => {
            actions.loadAuditData()
        },
        [marketingAnalyticsSettingsLogic.actionTypes.updateCampaignFieldPreferences]: () => {
            actions.loadAuditData()
        },
        [marketingAnalyticsSettingsLogic.actionTypes.updateCampaignNameMappings]: () => {
            actions.loadAuditData()
        },
        [marketingAnalyticsSettingsLogic.actionTypes.updateCustomSourceMappings]: () => {
            actions.loadAuditData()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAuditData()
    }),
])
