import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import {
    MARKETING_INTEGRATION_CONFIGS,
    type MarketingAnalyticsConfig,
    MatchField,
    type NativeMarketingSource,
    VALID_NATIVE_MARKETING_SOURCES,
} from '~/queries/schema/schema-general'

import type { CurrencyCode } from '../../../../../../queries/schema/schema-general'
import { getGlobalCampaignMapping } from '../components/NonIntegratedConversionsTable/mappingUtils'
import { similarityScore } from '../components/settings/stringSimilarity'
import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from './marketingAnalyticsTilesLogic'

export type UtmIssueKind = 'not_linked' | 'name_collision' | 'no_tagged_events' | 'unknown_source'

export type SuggestedAction = 'fix_platform_urls' | 'add_source_mapping' | 'switch_to_id_match'

export interface AlternativeSource {
    utm_source: string
    event_count: number
}

export interface UtmIssue {
    field: string
    severity: 'error' | 'warning'
    kind: UtmIssueKind
    message: string
    alternative_sources: AlternativeSource[]
    shared_with_integrations: string[]
    suggested_actions: SuggestedAction[]
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

/** Why a mapping is being proposed — drives the copy shown next to each pair. */
export type MappingReason = 'case_only' | 'near_miss' | 'manual'

export interface MappingPair {
    integration: NativeMarketingSource
    /** Key written into `campaign_name_mappings` — the campaign's name or ID, per the integration's match field. */
    matchValue: string
    /** Always the campaign name, for display, even when `matchValue` is the ID. */
    campaignName: string
    utmCampaign: string
    reason: MappingReason
}

// Pairs below this similarity are too speculative to propose unless the user picked both sides.
const NEAR_MISS_THRESHOLD = 0.8

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

/** Audit `source_name` ("google") -> integration key ("GoogleAds"). */
export const SOURCE_TO_INTEGRATION: Record<string, NativeMarketingSource> = Object.fromEntries(
    VALID_NATIVE_MARKETING_SOURCES.map((source) => [MARKETING_INTEGRATION_CONFIGS[source].primarySource, source])
)

function integrationForCampaign(campaign: CampaignAuditResult): NativeMarketingSource | null {
    return SOURCE_TO_INTEGRATION[campaign.source_name.toLowerCase()] ?? null
}

/** The campaign value `utm_campaign` is compared against, honouring the integration's match field. */
function matchValueForCampaign(campaign: CampaignAuditResult, config: MarketingAnalyticsConfig | null): string {
    const integration = integrationForCampaign(campaign)
    const matchField = (integration && config?.campaign_field_preferences?.[integration]?.match_field) || null
    return matchField === MatchField.CAMPAIGN_ID ? campaign.campaign_id : campaign.campaign_name
}

function buildPair(
    campaign: CampaignAuditResult,
    utmCampaign: string,
    reason: MappingReason,
    config: MarketingAnalyticsConfig | null
): MappingPair | null {
    const integration = integrationForCampaign(campaign)
    if (!integration) {
        return null
    }
    const matchValue = matchValueForCampaign(campaign, config)
    if (!matchValue) {
        return null
    }
    return { integration, matchValue, campaignName: campaign.campaign_name, utmCampaign, reason }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface utmAuditLogicValues {
    marketingAnalyticsConfig: MarketingAnalyticsConfig | null // marketingAnalyticsSettingsLogic
    baseCurrency: CurrencyCode // teamLogic
    currentTeamId: number | null // teamLogic
    activeTab: HealthTab
    aggregatedUtmSources: AggregatedUtmSource[]
    allMappedSources: Set<string>
    auditData: UtmAuditResponse | null
    auditDataFailure: string | null
    auditDataLoading: boolean
    autoMappingSuggestions: MappingPair[]
    availableSources: string[]
    campaignSearch: string
    campaignsWithoutUtmCount: number
    filteredCampaigns: CampaignAuditResult[]
    pendingMappings: MappingPair[]
    primarySelectedCampaign: string | null
    selectedCampaigns: string[]
    selectedCampaignsData: CampaignAuditResult[]
    selectedUtmCampaigns: string[]
    sortedUtmCampaigns: UtmEvent[]
    sourceFilter: string | null
    totalUtmSourcesCount: number
    unmappedSourcesCount: number
    utmSearch: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface utmAuditLogicActions {
    reloadAll: () => {} // dataNodeCollectionLogic
    updateCampaignNameMappings: (campaignNameMappings: Record<string, Record<string, string[]>>) => {
        campaignNameMappings: Record<string, Record<string, string[]>>
    } // marketingAnalyticsSettingsLogic
    applyMappings: (pairs: MappingPair[]) => {
        pairs: MappingPair[]
    }
    clearMappingSelection: () => {
        value: true
    }
    loadAuditData: () => any
    loadAuditDataFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAuditDataSuccess: (
        auditData: UtmAuditResponse,
        payload?: any
    ) => {
        auditData: UtmAuditResponse
        payload?: any
    }
    setActiveTab: (tab: HealthTab) => {
        tab: HealthTab
    }
    setCampaignSearch: (search: string) => {
        search: string
    }
    setSelectedCampaigns: (campaignNames: string[]) => {
        campaignNames: string[]
    }
    setSelectedUtmCampaigns: (utmCampaigns: string[]) => {
        utmCampaigns: string[]
    }
    setSourceFilter: (source: string | null) => {
        source: string | null
    }
    setUtmSearch: (search: string) => {
        search: string
    }
    toggleCampaign: (campaignName: string) => {
        campaignName: string
    }
    toggleUtmCampaign: (utmCampaign: string) => {
        utmCampaign: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface utmAuditLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        availableSources: (auditData: UtmAuditResponse | null) => string[]
        filteredCampaigns: (
            auditData: UtmAuditResponse | null,
            sourceFilter: string | null,
            campaignSearch: string
        ) => CampaignAuditResult[]
        campaignsWithoutUtmCount: (auditData: UtmAuditResponse | null) => number
        totalUtmSourcesCount: (auditData: UtmAuditResponse | null) => number
        unmappedSourcesCount: (auditData: UtmAuditResponse | null, allMappedSources: Set<string>) => number
        selectedCampaignsData: (
            auditData: UtmAuditResponse | null,
            selectedCampaigns: string[]
        ) => CampaignAuditResult[]
        primarySelectedCampaign: (selectedCampaigns: string[]) => string | null
        sortedUtmCampaigns: (
            auditData: UtmAuditResponse | null,
            primarySelectedCampaign: string | null,
            utmSearch: string
        ) => UtmEvent[]
        pendingMappings: (
            selectedCampaignsData: CampaignAuditResult[],
            selectedUtmCampaigns: string[],
            marketingAnalyticsConfig: MarketingAnalyticsConfig | null
        ) => MappingPair[]
        autoMappingSuggestions: (
            auditData: UtmAuditResponse | null,
            sourceFilter: string | null,
            marketingAnalyticsConfig: MarketingAnalyticsConfig | null
        ) => MappingPair[]
        allMappedSources: (marketingAnalyticsConfig: MarketingAnalyticsConfig | null) => Set<string>
        aggregatedUtmSources: (
            auditData: UtmAuditResponse | null,
            utmSearch: string,
            allMappedSources: Set<string>,
            marketingAnalyticsConfig: MarketingAnalyticsConfig | null
        ) => AggregatedUtmSource[]
    }
}

export type utmAuditLogicType = MakeLogicType<
    utmAuditLogicValues,
    utmAuditLogicActions,
    Record<string, any>,
    utmAuditLogicMeta
>

export const utmAuditLogic = kea<utmAuditLogicType>([
    path(['scenes', 'webAnalytics', 'utmAuditLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId', 'baseCurrency'],
            marketingAnalyticsSettingsLogic,
            ['marketingAnalyticsConfig'],
        ],
        actions: [
            dataNodeCollectionLogic({ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }),
            ['reloadAll'],
            marketingAnalyticsSettingsLogic,
            ['updateCampaignNameMappings'],
        ],
    })),
    actions({
        setActiveTab: (tab: HealthTab) => ({ tab }),
        toggleCampaign: (campaignName: string) => ({ campaignName }),
        toggleUtmCampaign: (utmCampaign: string) => ({ utmCampaign }),
        setSelectedCampaigns: (campaignNames: string[]) => ({ campaignNames }),
        setSelectedUtmCampaigns: (utmCampaigns: string[]) => ({ utmCampaigns }),
        clearMappingSelection: true,
        applyMappings: (pairs: MappingPair[]) => ({ pairs }),
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
        selectedCampaigns: [
            [] as string[],
            {
                toggleCampaign: (current, { campaignName }) =>
                    current.includes(campaignName)
                        ? current.filter((c) => c !== campaignName)
                        : [...current, campaignName],
                setSelectedCampaigns: (_, { campaignNames }) => [...new Set(campaignNames)],
                setSourceFilter: () => [],
                clearMappingSelection: () => [],
            },
        ],
        selectedUtmCampaigns: [
            [] as string[],
            {
                toggleUtmCampaign: (current, { utmCampaign }) =>
                    current.includes(utmCampaign)
                        ? current.filter((c) => c !== utmCampaign)
                        : [...current, utmCampaign],
                setSelectedUtmCampaigns: (_, { utmCampaigns }) => [...new Set(utmCampaigns)],
                setSourceFilter: () => [],
                clearMappingSelection: () => [],
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

        // Selected campaign data (for the Map campaigns bar)
        selectedCampaignsData: [
            (s) => [s.auditData, s.selectedCampaigns],
            (auditData: UtmAuditResponse | null, selectedCampaigns: string[]): CampaignAuditResult[] => {
                if (!auditData || selectedCampaigns.length === 0) {
                    return []
                }
                const selected = new Set(selectedCampaigns)
                return auditData.results.filter((r) => selected.has(r.campaign_name))
            },
        ],
        // Drives the similarity sort of the UTM panel — only the first pick, so the ordering
        // doesn't churn as more campaigns are added to a bulk selection.
        primarySelectedCampaign: [
            (s) => [s.selectedCampaigns],
            (selectedCampaigns: string[]): string | null => selectedCampaigns[0] ?? null,
        ],

        // Campaign tab — right panel
        sortedUtmCampaigns: [
            (s) => [s.auditData, s.primarySelectedCampaign, s.utmSearch],
            (
                auditData: UtmAuditResponse | null,
                primarySelectedCampaign: string | null,
                search: string
            ): UtmEvent[] => {
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
                if (primarySelectedCampaign) {
                    return [...events].sort(
                        (a, b) =>
                            similarityScore(primarySelectedCampaign, b.utm_campaign) -
                            similarityScore(primarySelectedCampaign, a.utm_campaign)
                    )
                }
                return events
            },
        ],

        // What "Map campaigns" would write. One campaign selected means every selected
        // utm_campaign maps to it; with several, each utm_campaign goes to its closest
        // selected campaign so a multi-select maps in a single action.
        pendingMappings: [
            (s) => [s.selectedCampaignsData, s.selectedUtmCampaigns, s.marketingAnalyticsConfig],
            (
                selectedCampaignsData: CampaignAuditResult[],
                selectedUtmCampaigns: string[],
                config: MarketingAnalyticsConfig | null
            ): MappingPair[] => {
                if (selectedCampaignsData.length === 0 || selectedUtmCampaigns.length === 0) {
                    return []
                }
                const onlyOneCampaign = selectedCampaignsData.length === 1
                const pairs: MappingPair[] = []
                for (const utmCampaign of selectedUtmCampaigns) {
                    if (getGlobalCampaignMapping(utmCampaign, config)) {
                        continue
                    }
                    let best: CampaignAuditResult | null = null
                    let bestScore = 0
                    for (const campaign of selectedCampaignsData) {
                        const score = similarityScore(utmCampaign, matchValueForCampaign(campaign, config))
                        if (score > bestScore) {
                            best = campaign
                            bestScore = score
                        }
                    }
                    // With a single campaign picked the intent is explicit, so map regardless of
                    // how different the strings look. Across several, require a close match.
                    if (!best || (!onlyOneCampaign && bestScore < NEAR_MISS_THRESHOLD)) {
                        continue
                    }
                    const pair = buildPair(best, utmCampaign, 'manual', config)
                    if (pair) {
                        pairs.push(pair)
                    }
                }
                return pairs
            },
        ],

        // Mappings we can propose without any selection. Case-only differences come first:
        // the audit compares case-insensitively but attribution joins on the raw strings, so
        // these look linked here yet never attribute until an explicit mapping exists.
        autoMappingSuggestions: [
            (s) => [s.auditData, s.sourceFilter, s.marketingAnalyticsConfig],
            (
                auditData: UtmAuditResponse | null,
                sourceFilter: string | null,
                config: MarketingAnalyticsConfig | null
            ): MappingPair[] => {
                if (!auditData) {
                    return []
                }
                const campaigns = sourceFilter
                    ? auditData.results.filter((r) => r.source_name === sourceFilter)
                    : auditData.results
                const utmCampaigns = [...new Set(auditData.all_utm_events.map((e) => e.utm_campaign))]

                const caseOnly: MappingPair[] = []
                const nearMiss: MappingPair[] = []
                const claimedUtm = new Set<string>()

                for (const campaign of campaigns) {
                    const matchValue = matchValueForCampaign(campaign, config)
                    if (!matchValue) {
                        continue
                    }
                    const normalized = matchValue.toLowerCase().trim()

                    let bestNearMiss: string | null = null
                    let bestScore = 0
                    for (const utmCampaign of utmCampaigns) {
                        if (claimedUtm.has(utmCampaign) || getGlobalCampaignMapping(utmCampaign, config)) {
                            continue
                        }
                        const utmNormalized = utmCampaign.toLowerCase().trim()
                        if (utmNormalized === normalized) {
                            if (utmCampaign !== matchValue) {
                                const pair = buildPair(campaign, utmCampaign, 'case_only', config)
                                if (pair) {
                                    caseOnly.push(pair)
                                    claimedUtm.add(utmCampaign)
                                }
                            }
                            // An exact match (case included) needs nothing; either way this
                            // campaign is resolved, so don't also propose a fuzzy candidate.
                            bestNearMiss = null
                            break
                        }
                        const score = similarityScore(matchValue, utmCampaign)
                        if (score >= NEAR_MISS_THRESHOLD && score > bestScore) {
                            bestNearMiss = utmCampaign
                            bestScore = score
                        }
                    }

                    // Only propose a fuzzy pair for campaigns the audit already flags — a
                    // healthy campaign doesn't need a guess bolted onto it.
                    if (bestNearMiss && campaign.issues.length > 0) {
                        const pair = buildPair(campaign, bestNearMiss, 'near_miss', config)
                        if (pair) {
                            nearMiss.push(pair)
                            claimedUtm.add(bestNearMiss)
                        }
                    }
                }

                return [...caseOnly, ...nearMiss]
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
    listeners(({ actions, values }) => ({
        applyMappings: ({ pairs }) => {
            if (pairs.length === 0) {
                return
            }
            const existing = values.marketingAnalyticsConfig?.campaign_name_mappings || {}
            const next: Record<string, Record<string, string[]>> = { ...existing }
            for (const pair of pairs) {
                const forIntegration = { ...next[pair.integration] }
                forIntegration[pair.matchValue] = [
                    ...new Set([...(forIntegration[pair.matchValue] || []), pair.utmCampaign]),
                ]
                next[pair.integration] = forIntegration
            }
            actions.updateCampaignNameMappings(next)
            actions.clearMappingSelection()
        },
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
