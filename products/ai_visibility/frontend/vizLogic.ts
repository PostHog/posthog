import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import {
    CompetitorComparison,
    DashboardData,
    MatrixCell,
    MentionRateDataPoint,
    PlatformMention,
    Prompt,
    ShareOfVoice,
    TopCitedSource,
    Topic,
} from './types'
import type { vizLogicType } from './vizLogicType'

export interface VizLogicProps {
    brand: string
}

export type DashboardTab = 'overview' | 'prompts' | 'competitors'

interface StartedResponse {
    workflow_id: string
    status: 'started' | 'running'
}

interface ReadyResponse {
    status: 'ready'
    run_id: string
    domain: string
    results: Record<string, unknown>
}

export type ApiResponse = StartedResponse | ReadyResponse

const POLL_INTERVAL_MS = 5000

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

    loaders(({ props }) => ({
        triggerResult: [
            null as ApiResponse | null,
            {
                loadTriggerResult: async () => {
                    if (!props.brand) {
                        throw new Error('Brand missing')
                    }
                    const response = await fetch('/api/ai_visibility/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ domain: props.brand }),
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

        // Extract topic from prompt text (first 2-3 words before suffix like "alternatives", "best", etc.)
        topics: [
            (s) => [s.prompts],
            (prompts: Prompt[]): Topic[] => {
                const suffixes = ['alternatives', 'competitors', 'best', 'pricing', 'reviews']
                const topicMap = new Map<string, Prompt[]>()

                for (const prompt of prompts) {
                    // Extract topic by removing common suffixes
                    let topic = prompt.text
                    for (const suffix of suffixes) {
                        if (topic.toLowerCase().endsWith(suffix)) {
                            topic = topic.slice(0, -suffix.length).trim()
                            break
                        }
                    }
                    // Capitalize first letter of each word
                    topic = topic
                        .split(' ')
                        .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
                        .join(' ')

                    const existing = topicMap.get(topic) || []
                    existing.push(prompt)
                    topicMap.set(topic, existing)
                }

                const topicsArray: Topic[] = []
                for (const [name, topicPrompts] of topicMap) {
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
                        .map(([compName]) => ({ name: compName }))

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

        // Top competitors sorted by visibility
        topCompetitors: [
            (s) => [s.competitorVisibility],
            (visibility: Record<string, number>): { name: string; visibility: number }[] => {
                return Object.entries(visibility)
                    .map(([name, vis]) => ({ name, visibility: vis }))
                    .sort((a, b) => b.visibility - a.visibility)
                    .slice(0, 10)
            },
        ],

        // Head-to-head competitor comparisons
        competitorComparisons: [
            (s) => [s.prompts, s.topCompetitors, s.topics],
            (
                prompts: Prompt[],
                topCompetitors: { name: string; visibility: number }[],
                topics: Topic[]
            ): CompetitorComparison[] => {
                const comparisons: CompetitorComparison[] = []

                for (const { name: competitor } of topCompetitors.slice(0, 6)) {
                    // Find prompts where both you and competitor are mentioned
                    const sharedPrompts = prompts.filter(
                        (p) => p.you_mentioned && p.competitors_mentioned.includes(competitor)
                    )

                    if (sharedPrompts.length === 0) {
                        continue
                    }

                    // Determine who "leads" based on position
                    let youLead = 0
                    let theyLead = 0
                    const youLeadsIn: { topic: string; percentage: number }[] = []
                    const theyLeadIn: { topic: string; percentage: number }[] = []

                    // Group by topic
                    const topicLeadership = new Map<string, { you: number; them: number; total: number }>()

                    for (const p of sharedPrompts) {
                        // Find which topic this prompt belongs to
                        const topic = topics.find((t) => t.prompts.some((tp) => tp.id === p.id))
                        const topicName = topic?.name || 'Other'

                        const existing = topicLeadership.get(topicName) || { you: 0, them: 0, total: 0 }

                        // Check your best position across platforms
                        let yourBestPos = Infinity
                        for (const plat of Object.values(p.platforms) as (PlatformMention | undefined)[]) {
                            if (plat?.mentioned && plat.position) {
                                yourBestPos = Math.min(yourBestPos, plat.position)
                            }
                        }

                        // Heuristic: if you're mentioned and they're just in competitors list, you likely rank better
                        // In reality we'd need their position data too
                        if (yourBestPos <= 2) {
                            youLead++
                            existing.you++
                        } else {
                            theyLead++
                            existing.them++
                        }
                        existing.total++
                        topicLeadership.set(topicName, existing)
                    }

                    // Convert to percentages
                    for (const [topicName, data] of topicLeadership) {
                        const youPct = Math.round((data.you / data.total) * 100)
                        const themPct = Math.round((data.them / data.total) * 100)
                        if (youPct >= themPct && youPct > 0) {
                            youLeadsIn.push({ topic: topicName, percentage: youPct })
                        } else if (themPct > 0) {
                            theyLeadIn.push({ topic: topicName, percentage: themPct })
                        }
                    }

                    comparisons.push({
                        competitor,
                        sharedPrompts: sharedPrompts.length,
                        youLeadPercentage:
                            youLead + theyLead > 0 ? Math.round((youLead / (youLead + theyLead)) * 100) : 50,
                        youLeadsIn: youLeadsIn.sort((a, b) => b.percentage - a.percentage).slice(0, 5),
                        theyLeadIn: theyLeadIn.sort((a, b) => b.percentage - a.percentage).slice(0, 5),
                    })
                }

                return comparisons
            },
        ],

        // Matrix data: competitors vs topics visibility
        competitorTopicsMatrix: [
            (s) => [s.topics, s.topCompetitors],
            (topics: Topic[], topCompetitors: { name: string; visibility: number }[]): MatrixCell[] => {
                const cells: MatrixCell[] = []

                for (const topic of topics) {
                    for (const { name: competitor } of topCompetitors) {
                        // Calculate this competitor's visibility in this topic
                        const relevantPrompts = topic.prompts.filter((p) =>
                            p.competitors_mentioned.includes(competitor)
                        )
                        const visibility =
                            topic.prompts.length > 0
                                ? Math.round((relevantPrompts.length / topic.prompts.length) * 100)
                                : 0

                        cells.push({
                            topic: topic.name,
                            competitor,
                            visibility,
                            avgRank: null, // We don't have competitor rank data
                        })
                    }
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
    }),

    listeners(({ actions, values, cache }) => ({
        loadTriggerResultSuccess: ({ triggerResult }) => {
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

    afterMount(({ actions }) => {
        actions.loadTriggerResult()
    }),

    beforeUnmount(({ cache }) => {
        if (cache.pollIntervalId) {
            clearInterval(cache.pollIntervalId)
        }
    }),
])
