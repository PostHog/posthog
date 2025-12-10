import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import { BRAND_DISPLAY_NAMES, MOCK_DATA_BY_BRAND } from './mockData'
import { DashboardData, Prompt } from './types'
import type { vizLogicType } from './vizLogicType'

export interface VizLogicProps {
    brand: string
}

export const vizLogic = kea<vizLogicType>([
    path(['products', 'ai_visibility', 'frontend', 'vizLogic']),
    props({} as VizLogicProps),
    key((props) => props.brand || 'posthog'),

    actions({
        setSelectedPrompt: (prompt: Prompt | null) => ({ prompt }),
        setFilterCategory: (category: 'all' | 'commercial' | 'informational' | 'navigational') => ({ category }),
    }),

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
    }),

    selectors({
        brand: [() => [(_, props) => props.brand], (brand) => brand],
        brandDisplayName: [
            (s) => [s.brand],
            (brand) => BRAND_DISPLAY_NAMES[brand] || brand.charAt(0).toUpperCase() + brand.slice(1),
        ],
        data: [
            (s) => [s.brand],
            (brand): DashboardData => {
                return MOCK_DATA_BY_BRAND[brand] || MOCK_DATA_BY_BRAND['posthog']
            },
        ],
        visibilityScore: [(s) => [s.data], (data) => data.visibility_score],
        scoreChange: [(s) => [s.data], (data) => data.score_change],
        scoreChangePeriod: [(s) => [s.data], (data) => data.score_change_period],
        shareOfVoice: [(s) => [s.data], (data) => data.share_of_voice],
        mentionRateOverTime: [(s) => [s.data], (data) => data.mention_rate_over_time],
        prompts: [(s) => [s.data], (data) => data.prompts],

        filteredPrompts: [
            (s) => [s.prompts, s.filterCategory],
            (prompts, category) => {
                if (category === 'all') {
                    return prompts
                }
                return prompts.filter((p) => p.category === category)
            },
        ],

        chartData: [
            (s) => [s.mentionRateOverTime],
            (mentionRate) => {
                const dates = mentionRate.map((d) => d.date)
                const keys = Object.keys(mentionRate[0] || {}).filter((k) => k !== 'date')

                const series = keys.map((key, index) => ({
                    id: index,
                    label: key === 'you' ? 'You' : key,
                    data: mentionRate.map((d) => (typeof d[key] === 'number' ? (d[key] as number) * 100 : 0)),
                    dates,
                }))

                return { dates, series }
            },
        ],

        shareOfVoiceChartData: [
            (s) => [s.shareOfVoice, s.brandDisplayName],
            (sov, brandName) => {
                const entries = [
                    { name: brandName, value: sov.you },
                    ...Object.entries(sov.competitors).map(([name, value]) => ({ name, value })),
                ]
                return entries.sort((a, b) => b.value - a.value)
            },
        ],

        mentionStats: [
            (s) => [s.prompts],
            (prompts) => {
                const total = prompts.length
                const mentioned = prompts.filter((p) => p.you_mentioned).length
                const topPosition = prompts.filter((p) => {
                    return Object.values(p.platforms).some((plat) => plat?.mentioned && plat.position === 1)
                }).length
                const cited = prompts.filter((p) => {
                    return Object.values(p.platforms).some((plat) => plat?.mentioned && plat.cited)
                }).length

                return { total, mentioned, topPosition, cited }
            },
        ],

        availableBrands: [() => [], () => Object.keys(MOCK_DATA_BY_BRAND)],
    }),
])
