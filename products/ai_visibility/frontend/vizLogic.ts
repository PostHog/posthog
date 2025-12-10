import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import {
    CompetitorComparison,
    DashboardData,
    MatrixCell,
    MentionRateDataPoint,
    PlatformMention,
    Prompt,
    ShareOfVoice,
    SourceDetails,
    TopCitedSource,
    Topic,
    TopicLead,
} from './types'
import type { vizLogicType } from './vizLogicType'

export interface VizLogicProps {
    brand: string
}

export type DashboardTab = 'overview' | 'prompts' | 'competitors' | 'sources'

export type ProgressStep =
    | 'starting'
    | 'extracting_info'
    | 'generating_topics'
    | 'generating_prompts'
    | 'running_ai_calls'
    | 'combining_results'
    | 'saving'
    | 'complete'

export const PROGRESS_STEPS: { step: ProgressStep; label: string; index: number }[] = [
    { step: 'starting', label: 'Starting', index: 0 },
    { step: 'extracting_info', label: 'Extracting business info', index: 1 },
    { step: 'generating_topics', label: 'Generating topics', index: 2 },
    { step: 'generating_prompts', label: 'Generating prompts', index: 3 },
    { step: 'running_ai_calls', label: 'Running AI calls', index: 4 },
    { step: 'combining_results', label: 'Combining results', index: 5 },
    { step: 'saving', label: 'Saving results', index: 6 },
    { step: 'complete', label: 'Complete', index: 7 },
]

interface StartedResponse {
    workflow_id: string
    run_id: string
    status: 'started' | 'running'
    progress_step: ProgressStep
    created_at: string
}

interface ReadyResponse {
    status: 'ready'
    run_id: string
    domain: string
    results: Record<string, unknown>
}

export type ApiResponse = StartedResponse | ReadyResponse

const POLL_INTERVAL_MS = 1000

export const vizLogic = kea<vizLogicType>([
    path(['products', 'ai_visibility', 'frontend', 'vizLogic']),
    props({} as VizLogicProps),
    key((props) => props.brand || 'posthog'),

    actions({
        setSelectedPrompt: (prompt: Prompt | null) => ({ prompt }),
        setFilterCategory: (category: 'all' | 'commercial' | 'informational' | 'navigational') => ({ category }),
        setActiveTab: (tab: DashboardTab) => ({ tab }),
        startPolling: true,
        stopPolling: true,
    }),

    loaders(({ props, values }) => ({
        triggerResult: [
            null as ApiResponse | null,
            {
                loadTriggerResult: async () => {
                    if (!props.brand) {
                        throw new Error('Brand missing')
                    }
                    const body: { domain: string; run_id?: string } = { domain: props.brand }
                    if (values.pollingRunId) {
                        body.run_id = values.pollingRunId
                    }
                    const response = await fetch('/api/ai_visibility/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body),
                    })
                    if (!response.ok) {
                        const data = await response.json().catch(() => ({}))
                        const message = data?.error || `Request failed with status ${response.status}`
                        throw new Error(message)
                    }
                    return await response.json()
                },
                forceNewRun: async () => {
                    if (!props.brand) {
                        throw new Error('Brand missing')
                    }
                    const response = await fetch('/api/ai_visibility/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ domain: props.brand, force: true }),
                    })
                    if (!response.ok) {
                        const data = await response.json().catch(() => ({}))
                        const message = data?.error || `Request failed with status ${response.status}`
                        throw new Error(message)
                    }
                    return await response.json()
                },
            },
        ],
    })),

    reducers({
        selectedPrompt: [
            null as Prompt | null,
            {
                setSelectedPrompt: (_, { prompt }) => prompt,
            },
        ],
        filterCategory: [
            'all' as 'all' | 'commercial' | 'informational' | 'navigational',
            {
                setFilterCategory: (_, { category }) => category,
            },
        ],
        activeTab: [
            'overview' as DashboardTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        lastError: [
            null as string | null,
            {
                loadTriggerResultFailure: (_, { error }) => error ?? 'Failed to start workflow',
                loadTriggerResultSuccess: () => null,
                forceNewRunFailure: (_, { error }) => error ?? 'Failed to start workflow',
                forceNewRunSuccess: () => null,
            },
        ],
        pollingRunId: [
            null as string | null,
            {
                loadTriggerResultSuccess: (_, { triggerResult }) =>
                    triggerResult?.status === 'started' || triggerResult?.status === 'running'
                        ? (triggerResult as StartedResponse).run_id
                        : null,
                forceNewRunSuccess: (_, { triggerResult }) =>
                    triggerResult?.status === 'started' || triggerResult?.status === 'running'
                        ? (triggerResult as StartedResponse).run_id
                        : null,
            },
        ],
    }),

    selectors({
        brand: [() => [(_, props) => props.brand], (brand) => brand],
        brandDisplayName: [(s) => [s.brand], (brand: string) => brand.charAt(0).toUpperCase() + brand.slice(1)],

        data: [
            (s) => [s.results],
            (results): DashboardData | null => {
                if (results) {
                    return results as unknown as DashboardData
                }
                return null
            },
        ],

        // Backend selectors
        workflowId: [
            (s) => [s.triggerResult],
            (triggerResult): string | null => {
                if (triggerResult?.status === 'started' || triggerResult?.status === 'running') {
                    return triggerResult.workflow_id
                }
                return null
            },
        ],
        isPolling: [
            (s) => [s.triggerResult],
            (triggerResult): boolean => triggerResult?.status === 'started' || triggerResult?.status === 'running',
        ],
        createdAt: [
            (s) => [s.triggerResult],
            (triggerResult): string | null => {
                if (triggerResult?.status === 'started' || triggerResult?.status === 'running') {
                    return triggerResult.created_at
                }
                return null
            },
        ],
        progressStep: [
            (s) => [s.triggerResult],
            (triggerResult: ApiResponse | null): ProgressStep => {
                if (triggerResult?.status === 'started' || triggerResult?.status === 'running') {
                    return triggerResult.progress_step
                }
                if (triggerResult?.status === 'ready') {
                    return 'complete'
                }
                return 'starting'
            },
        ],
        progressPercent: [
            (s) => [s.triggerResult],
            (triggerResult: ApiResponse | null): number => {
                let step: ProgressStep = 'starting'
                if (triggerResult?.status === 'started' || triggerResult?.status === 'running') {
                    step = triggerResult.progress_step
                } else if (triggerResult?.status === 'ready') {
                    step = 'complete'
                }
                const stepInfo = PROGRESS_STEPS.find((s) => s.step === step)
                if (!stepInfo) {
                    return 0
                }
                return Math.round((stepInfo.index / (PROGRESS_STEPS.length - 1)) * 100)
            },
        ],
        progressLabel: [
            (s) => [s.triggerResult],
            (triggerResult: ApiResponse | null): string => {
                let step: ProgressStep = 'starting'
                if (triggerResult?.status === 'started' || triggerResult?.status === 'running') {
                    step = triggerResult.progress_step
                } else if (triggerResult?.status === 'ready') {
                    step = 'complete'
                }
                const stepInfo = PROGRESS_STEPS.find((s) => s.step === step)
                return stepInfo?.label || 'Processing'
            },
        ],
        isReady: [(s) => [s.triggerResult], (triggerResult): boolean => triggerResult?.status === 'ready'],
        results: [
            (s) => [s.triggerResult],
            (triggerResult): Record<string, unknown> | null => {
                if (triggerResult?.status === 'ready') {
                    return triggerResult.results
                }
                return null
            },
        ],
        runId: [
            (s) => [s.triggerResult],
            (triggerResult): string | null => {
                if (triggerResult?.status === 'ready') {
                    return triggerResult.run_id
                }
                return null
            },
        ],

        // Dashboard selectors
        visibilityScore: [(s) => [s.data], (data) => data?.visibility_score ?? 0],
        scoreChange: [(s) => [s.data], (data) => data?.score_change ?? 0],
        scoreChangePeriod: [(s) => [s.data], (data) => data?.score_change_period ?? 'week'],
        shareOfVoice: [(s) => [s.data], (data) => data?.share_of_voice ?? { you: 0, competitors: {} }],
        mentionRateOverTime: [(s) => [s.data], (data) => data?.mention_rate_over_time ?? []],
        prompts: [(s) => [s.data], (data) => data?.prompts ?? []],

        filteredPrompts: [
            (s) => [s.prompts, s.filterCategory],
            (prompts: Prompt[], category): Prompt[] => {
                if (category === 'all') {
                    return prompts
                }
                return prompts.filter((p: Prompt) => p.category === category)
            },
        ],

        chartData: [
            (s) => [s.mentionRateOverTime],
            (mentionRate: MentionRateDataPoint[]) => {
                if (!mentionRate.length) {
                    return {
                        dates: [] as string[],
                        series: [] as { id: number; label: string; data: number[]; dates: string[] }[],
                    }
                }
                const dates = mentionRate.map((d: MentionRateDataPoint) => d.date)
                const keys = Object.keys(mentionRate[0] || {}).filter((k) => k !== 'date')

                const series = keys.map((key, index) => ({
                    id: index,
                    label: key === 'you' ? 'You' : key,
                    data: mentionRate.map((d: MentionRateDataPoint) =>
                        typeof d[key] === 'number' ? (d[key] as number) * 100 : 0
                    ),
                    dates,
                }))

                return { dates, series }
            },
        ],

        shareOfVoiceChartData: [
            (s) => [s.shareOfVoice, s.brandDisplayName],
            (sov: ShareOfVoice, brandName: string) => {
                const entries = [
                    { name: brandName, value: sov.you },
                    ...Object.entries(sov.competitors).map(([name, value]) => ({ name, value })),
                ]
                return entries.sort((a, b) => b.value - a.value)
            },
        ],

        mentionStats: [
            (s) => [s.prompts],
            (prompts: Prompt[]) => {
                const total = prompts.length
                const mentioned = prompts.filter((p: Prompt) => p.you_mentioned).length
                const topPosition = prompts.filter((p: Prompt) => {
                    return (Object.values(p.platforms) as (PlatformMention | undefined)[]).some(
                        (plat) => plat?.mentioned && plat.position === 1
                    )
                }).length
                const cited = prompts.filter((p: Prompt) => {
                    return (Object.values(p.platforms) as (PlatformMention | undefined)[]).some(
                        (plat) => plat?.mentioned && plat.cited
                    )
                }).length

                return { total, mentioned, topPosition, cited }
            },
        ],

        // Group prompts by their topic field
        topics: [
            (s) => [s.prompts],
            (prompts: Prompt[]): Topic[] => {
                const topicMap = new Map<string, Prompt[]>()

                for (const prompt of prompts) {
                    const topic = prompt.topic || 'General'
                    const existing = topicMap.get(topic) || []
                    existing.push(prompt)
                    topicMap.set(topic, existing)
                }

                const topicsArray: Topic[] = []
                for (const [name, topicPrompts] of topicMap) {
                    const competitorDetails = new Map<string, { icon?: string }>()
                    for (const p of topicPrompts) {
                        const comps = p.competitors && p.competitors.length > 0 ? p.competitors : []
                        for (const comp of comps) {
                            const icon =
                                comp.logo_url || (comp.domain ? `https://logo.clearbit.com/${comp.domain}` : undefined)
                            const existing = competitorDetails.get(comp.name)
                            if (!existing || (icon && !existing.icon)) {
                                competitorDetails.set(comp.name, { icon })
                            }
                        }
                    }

                    const mentioned = topicPrompts.filter((p) => p.you_mentioned).length
                    const visibility = topicPrompts.length > 0 ? (mentioned / topicPrompts.length) * 100 : 0

                    // Calculate average rank across all platforms where mentioned
                    let totalRank = 0
                    let rankCount = 0
                    let citationCount = 0
                    for (const p of topicPrompts) {
                        for (const plat of Object.values(p.platforms) as (PlatformMention | undefined)[]) {
                            if (plat?.mentioned && plat.position) {
                                totalRank += plat.position
                                rankCount++
                            }
                            if (plat?.cited) {
                                citationCount++
                            }
                        }
                    }
                    const avgRank = rankCount > 0 ? totalRank / rankCount : 0

                    // Collect all competitors and count occurrences
                    const compCounts = new Map<string, number>()
                    for (const p of topicPrompts) {
                        for (const comp of p.competitors_mentioned) {
                            compCounts.set(comp, (compCounts.get(comp) || 0) + 1)
                        }
                    }
                    const topCompetitors = [...compCounts.entries()]
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 4)
                        .map(([compName]) => ({
                            name: compName,
                            icon: competitorDetails.get(compName)?.icon,
                        }))

                    // Relevancy is based on how many prompts mention any competitor (topic is active in market)
                    const relevancy =
                        topicPrompts.length > 0
                            ? (topicPrompts.filter((p) => p.competitors_mentioned.length > 0).length /
                                  topicPrompts.length) *
                              100
                            : 0

                    topicsArray.push({
                        name,
                        promptCount: topicPrompts.length,
                        visibility: Math.round(visibility),
                        relevancy: Math.round(relevancy),
                        avgRank: avgRank > 0 ? Math.round(avgRank * 10) / 10 : 0,
                        citations: citationCount,
                        topCompetitors,
                        prompts: topicPrompts,
                    })
                }

                return topicsArray.sort((a, b) => b.visibility - a.visibility)
            },
        ],

        // Competitor visibility percentages across all prompts
        competitorVisibility: [
            (s) => [s.prompts],
            (prompts: Prompt[]): Record<string, number> => {
                const compMentions = new Map<string, number>()
                const total = prompts.length

                for (const p of prompts) {
                    for (const comp of p.competitors_mentioned) {
                        compMentions.set(comp, (compMentions.get(comp) || 0) + 1)
                    }
                }

                const result: Record<string, number> = {}
                for (const [name, count] of compMentions) {
                    result[name] = Math.round((count / total) * 100)
                }
                return result
            },
        ],

        // Build name → domain map from competitor objects in prompts
        competitorDomains: [
            (s) => [s.prompts],
            (prompts: Prompt[]): Record<string, string> => {
                const domains: Record<string, string> = {}
                for (const p of prompts) {
                    for (const comp of p.competitors ?? []) {
                        if (comp.name && comp.domain) {
                            domains[comp.name] = comp.domain
                        }
                    }
                }
                return domains
            },
        ],

        // Top competitors sorted by visibility
        topCompetitors: [
            (s) => [s.competitorVisibility, s.competitorDomains],
            (
                visibility: Record<string, number>,
                domains: Record<string, string>
            ): { name: string; visibility: number; domain?: string }[] => {
                return Object.entries(visibility)
                    .map(([name, vis]) => ({ name, visibility: vis, domain: domains[name] }))
                    .sort((a, b) => b.visibility - a.visibility)
                    .slice(0, 10)
            },
        ],

        // Head-to-head competitor comparisons based on mention counts
        competitorComparisons: [
            (s) => [s.prompts, s.topCompetitors, s.topics],
            (
                prompts: Prompt[],
                topCompetitors: { name: string; visibility: number }[],
                topics: Topic[]
            ): CompetitorComparison[] => {
                const comparisons: CompetitorComparison[] = []

                for (const { name: competitor } of topCompetitors.slice(0, 6)) {
                    // Count mentions across all prompts
                    let youMentioned = 0
                    let theyMentioned = 0
                    const youLeadsIn: TopicLead[] = []
                    const theyLeadIn: TopicLead[] = []

                    // Track per-topic mention counts
                    const topicMentions = new Map<string, { you: number; them: number; total: number }>()

                    // Initialize all topics
                    for (const topic of topics) {
                        topicMentions.set(topic.name, { you: 0, them: 0, total: 0 })
                    }

                    for (const p of prompts) {
                        const topic = topics.find((t) => t.prompts.some((tp) => tp.id === p.id))
                        const topicName = topic?.name || 'Other'

                        const existing = topicMentions.get(topicName) || { you: 0, them: 0, total: 0 }
                        existing.total++

                        if (p.you_mentioned) {
                            youMentioned++
                            existing.you++
                        }
                        if (p.competitors_mentioned.includes(competitor)) {
                            theyMentioned++
                            existing.them++
                        }

                        topicMentions.set(topicName, existing)
                    }

                    // Skip if competitor never mentioned
                    if (theyMentioned === 0) {
                        continue
                    }

                    // Calculate who leads in each topic (skip ties)
                    for (const [topicName, data] of topicMentions) {
                        if (data.total === 0) {
                            continue
                        }
                        const totalMentionsInTopic = data.you + data.them
                        if (totalMentionsInTopic === 0) {
                            continue
                        }
                        const youPct = (data.you / totalMentionsInTopic) * 100
                        const themPct = (data.them / totalMentionsInTopic) * 100

                        if (youPct > themPct) {
                            youLeadsIn.push({ topic: topicName, percentage: Math.round(youPct * 10) / 10 })
                        } else if (themPct > youPct) {
                            theyLeadIn.push({ topic: topicName, percentage: Math.round(themPct * 10) / 10 })
                        }
                        // Skip ties (youPct === themPct)
                    }

                    // Overall: what % of total mentions are yours vs theirs
                    const totalMentions = youMentioned + theyMentioned
                    const youLeadPercentage = totalMentions > 0 ? Math.round((youMentioned / totalMentions) * 100) : 50

                    comparisons.push({
                        competitor,
                        sharedPrompts: prompts.length,
                        youLeadPercentage,
                        youLeadsIn: youLeadsIn.sort((a, b) => b.percentage - a.percentage),
                        theyLeadIn: theyLeadIn.sort((a, b) => b.percentage - a.percentage),
                    })
                }

                return comparisons
            },
        ],

        // Matrix data: competitors vs topics visibility with rankings
        competitorTopicsMatrix: [
            (s) => [s.topics, s.topCompetitors, s.brandDisplayName],
            (
                topics: Topic[],
                topCompetitors: { name: string; visibility: number }[],
                brandName: string
            ): MatrixCell[] => {
                const cells: MatrixCell[] = []

                for (const topic of topics) {
                    // Count mentions for each competitor and the brand in this topic
                    const mentionCounts: { name: string; count: number }[] = []

                    // Add brand
                    const brandMentions = topic.prompts.filter((p) => p.you_mentioned).length
                    mentionCounts.push({ name: brandName, count: brandMentions })

                    // Add competitors
                    for (const { name: competitor } of topCompetitors) {
                        const count = topic.prompts.filter((p) => p.competitors_mentioned.includes(competitor)).length
                        mentionCounts.push({ name: competitor, count })
                    }

                    // Sort by count descending and assign ranks
                    mentionCounts.sort((a, b) => b.count - a.count)
                    const ranks = new Map<string, number>()
                    let currentRank = 1
                    for (let i = 0; i < mentionCounts.length; i++) {
                        // Handle ties: same count = same rank
                        if (i > 0 && mentionCounts[i].count < mentionCounts[i - 1].count) {
                            currentRank = i + 1
                        }
                        ranks.set(mentionCounts[i].name, mentionCounts[i].count > 0 ? currentRank : 0)
                    }

                    // Create cells for competitors (brand is handled separately in the component)
                    for (const { name: competitor } of topCompetitors) {
                        const count = topic.prompts.filter((p) => p.competitors_mentioned.includes(competitor)).length
                        const visibility =
                            topic.prompts.length > 0 ? Math.round((count / topic.prompts.length) * 100) : 0

                        cells.push({
                            topic: topic.name,
                            competitor,
                            visibility,
                            avgRank: ranks.get(competitor) ?? null,
                        })
                    }

                    // Also store brand's visibility and rank for this topic
                    const brandVisibility =
                        topic.prompts.length > 0 ? Math.round((brandMentions / topic.prompts.length) * 100) : 0
                    cells.push({
                        topic: topic.name,
                        competitor: brandName,
                        visibility: brandVisibility,
                        avgRank: ranks.get(brandName) ?? null,
                    })
                }

                return cells
            },
        ],

        // Brand's overall ranking (what position are they typically at?)
        brandRanking: [
            (s) => [s.topCompetitors, s.visibilityScore],
            (topCompetitors: { name: string; visibility: number }[], visibilityScore: number): number => {
                // Count how many competitors have higher visibility
                let rank = 1
                for (const comp of topCompetitors) {
                    if (comp.visibility > visibilityScore) {
                        rank++
                    }
                }
                return rank
            },
        ],

        // Top cited sources (domains mentioned in responses)
        topCitedSources: [
            (s) => [s.prompts],
            (prompts: Prompt[]): TopCitedSource[] => {
                // In real data we'd have actual cited URLs. For now derive from competitors
                const sourceCounts = new Map<string, number>()

                for (const p of prompts) {
                    // Count prompts where citations exist
                    for (const plat of Object.values(p.platforms) as (PlatformMention | undefined)[]) {
                        if (plat?.cited) {
                            // Use the brand name as proxy for source
                            for (const comp of p.competitors_mentioned.slice(0, 2)) {
                                const domain = `${comp.toLowerCase().replace(/\s+/g, '')}.com`
                                sourceCounts.set(domain, (sourceCounts.get(domain) || 0) + 1)
                            }
                        }
                    }
                }

                return [...sourceCounts.entries()]
                    .map(([domain, responseCount]) => ({ domain, responseCount }))
                    .sort((a, b) => b.responseCount - a.responseCount)
                    .slice(0, 6)
            },
        ],

        // Detailed source data for Sources tab
        sourceDetails: [
            (s) => [s.prompts],
            (prompts: Prompt[]): SourceDetails[] => {
                // Build domain stats from competitors in prompts
                const domainStats = new Map<string, { topics: Set<string>; responses: number; brandMentions: number }>()

                for (const p of prompts) {
                    // Get all domains mentioned in this prompt's competitors
                    const domains = new Set<string>()
                    for (const comp of p.competitors ?? []) {
                        if (comp.domain) {
                            domains.add(comp.domain)
                        }
                    }

                    // Update stats for each domain
                    for (const domain of domains) {
                        if (!domainStats.has(domain)) {
                            domainStats.set(domain, { topics: new Set(), responses: 0, brandMentions: 0 })
                        }
                        const stats = domainStats.get(domain)!
                        stats.topics.add(p.topic)
                        stats.responses++
                        if (p.you_mentioned) {
                            stats.brandMentions++
                        }
                    }
                }

                return [...domainStats.entries()]
                    .map(([domain, stats]) => ({
                        domain,
                        pages: stats.topics.size,
                        responses: stats.responses,
                        brandMentionRate:
                            stats.responses > 0 ? Math.round((stats.brandMentions / stats.responses) * 100) : 0,
                    }))
                    .sort((a, b) => b.responses - a.responses)
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        loadTriggerResultSuccess: ({ triggerResult }) => {
            if (triggerResult?.status === 'started' || triggerResult?.status === 'running') {
                actions.startPolling()
            } else if (triggerResult?.status === 'ready') {
                actions.stopPolling()
            }
        },
        forceNewRunSuccess: ({ triggerResult }) => {
            if (triggerResult?.status === 'started' || triggerResult?.status === 'running') {
                actions.startPolling()
            } else if (triggerResult?.status === 'ready') {
                actions.stopPolling()
            }
        },
        startPolling: () => {
            if (cache.pollIntervalId) {
                clearInterval(cache.pollIntervalId)
            }
            cache.pollIntervalId = setInterval(() => {
                if (!values.triggerResultLoading) {
                    actions.loadTriggerResult()
                }
            }, POLL_INTERVAL_MS)
        },
        stopPolling: () => {
            if (cache.pollIntervalId) {
                clearInterval(cache.pollIntervalId)
                cache.pollIntervalId = null
            }
        },
    })),

    actionToUrl(({ values }) => ({
        setActiveTab: () => {
            const hash = values.activeTab === 'overview' ? '' : `#${values.activeTab}`
            return [router.values.location.pathname, router.values.searchParams, hash]
        },
    })),

    urlToAction(({ actions, values }) => ({
        '/viz/:brand': () => {
            const hash = router.values.location.hash.replace('#', '')
            const tab = ['prompts', 'competitors', 'sources'].includes(hash) ? (hash as DashboardTab) : 'overview'
            if (tab !== values.activeTab) {
                actions.setActiveTab(tab)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTriggerResult()
        // Sync tab from URL hash on mount
        const hash = window.location.hash.replace('#', '')
        const tab = ['prompts', 'competitors', 'sources'].includes(hash) ? (hash as DashboardTab) : 'overview'
        if (tab !== 'overview') {
            actions.setActiveTab(tab)
        }
    }),

    beforeUnmount(({ cache }) => {
        if (cache.pollIntervalId) {
            clearInterval(cache.pollIntervalId)
        }
    }),
])
