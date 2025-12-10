import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { BRAND_DISPLAY_NAMES, MOCK_DATA_BY_BRAND } from './mockData'
import { DashboardData, MentionRateDataPoint, PlatformMention, Prompt, ShareOfVoice } from './types'
import type { vizLogicType } from './vizLogicType'

export interface VizLogicProps {
    brand: string
}

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
        brandDisplayName: [
            (s) => [s.brand],
            (brand) => BRAND_DISPLAY_NAMES[brand] || brand.charAt(0).toUpperCase() + brand.slice(1),
        ],

        hasMockData: [(s) => [s.brand], (brand): boolean => brand in MOCK_DATA_BY_BRAND],

        data: [
            (s) => [s.brand, s.results],
            (brand, results): DashboardData | null => {
                // Prefer real API results over mock data
                if (results) {
                    return results as DashboardData
                }
                return MOCK_DATA_BY_BRAND[brand] || null
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

        // Combined: show dashboard if we have mock data OR backend results
        hasData: [(s) => [s.hasMockData, s.isReady], (hasMockData, isReady): boolean => hasMockData || isReady],

        // Dashboard selectors (for mock data)
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

        availableBrands: [() => [], () => Object.keys(MOCK_DATA_BY_BRAND)],
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

    afterMount(({ actions, values }) => {
        // Only trigger backend if we don't have mock data
        if (!values.hasMockData) {
            actions.loadTriggerResult()
        }
    }),

    beforeUnmount(({ cache }) => {
        if (cache.pollIntervalId) {
            clearInterval(cache.pollIntervalId)
        }
    }),
])
