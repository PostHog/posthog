import { Meta } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { webAnalyticsLogic } from './webAnalyticsLogic'

const BUCKETS = ['2023-01-26', '2023-01-27', '2023-01-28', '2023-01-29', '2023-01-30', '2023-01-31', '2023-02-01']

const OVERVIEW_HUMAN = {
    columns: ['bucket', 'visitors', 'visitors_previous', 'google', 'google_previous', 'llm', 'llm_previous', 'pages'],
    results: [
        ['1970-01-01 00:00:00', 1430, 1210, 384, 361, 812, 260, 128],
        ...[170, 190, 165, 235, 210, 245, 215].map((visitors, index) => [
            `${BUCKETS[index]} 00:00:00`,
            visitors,
            0,
            Math.round(visitors * 0.42),
            0,
            Math.round(visitors * 0.03),
            0,
            0,
        ]),
    ],
}

const OVERVIEW_CRAWLER = {
    columns: ['bucket', 'crawls', 'crawls_previous', 'server_logs'],
    results: [
        ['1970-01-01 00:00:00', 88100, 78600, 214000],
        ...[9800, 11200, 10400, 14100, 13600, 15200, 13800].map((crawls, index) => [
            `${BUCKETS[index]} 00:00:00`,
            crawls,
            0,
            0,
        ]),
    ],
}

// A site with real traffic but no forwarded access logs and no AI referrals: the common shape today.
const OVERVIEW_HUMAN_NO_AI = {
    columns: OVERVIEW_HUMAN.columns,
    results: [['1970-01-01 00:00:00', 1430, 1210, 384, 361, 0, 0, 128]],
}

const OVERVIEW_CRAWLER_NONE = {
    columns: OVERVIEW_CRAWLER.columns,
    results: [['1970-01-01 00:00:00', 0, 0, 0]],
}

// Every metric tuple is [current, previous], except agent crawls, which is [crawls, distinct agents].
const PAGE_ROWS = [
    ['hedgebox.net/pricing', [172, 141], [50, 44], [121, 19], [900, 60], [16, 12], 94],
    ['hedgebox.net/docs/getting-started', [164, 152], [61, 58], [103, 61], [921, 60], [12, 13], 61],
    ['hedgebox.net/blog/why-hedgehogs-love-analytics', [162, 131], [45, 49], [117, 11], [889, 60], [14, 9], 132],
    ['hedgebox.net/', [157, 149], [42, 40], [114, 84], [944, 60], [15, 15], 78],
    ['hedgebox.net/features', [148, 119], [44, 41], [104, 17], [0, 0], [14, 11], 145],
    ['hedgebox.net/about', [143, 133], [49, 52], [93, 66], [18, 17], [15, 14], 96],
    ['hedgebox.net/docs/web-analytics', [137, 126], [42, 37], [95, 20], [861, 60], [16, 16], 112],
    ['localhost:8010/login', [2, 1], [0, 0], [0, 0], [0, 0], [0, 0], 585],
]

const LEADERBOARD = {
    columns: [
        'context.columns.breakdown_value',
        'context.columns.visitors',
        'context.columns.google_search',
        'context.columns.llm_referrals',
        'context.columns.agent_crawls',
        'context.columns.conversions',
        'context.columns.avg_time',
    ],
    results: PAGE_ROWS,
}

const LEADERBOARD_NO_AI = {
    columns: LEADERBOARD.columns,
    results: PAGE_ROWS.map((row) => [row[0], row[1], row[2], [0, 0], [0, 0], row[5], row[6]]),
}

const CANDIDATES = {
    columns: ['context.columns.breakdown_value'],
    results: PAGE_ROWS.map((row) => [row[0]]),
}

const trend = (label: string, values: number[]): Record<string, unknown> => ({
    results: [
        {
            action: { id: label, name: label, type: 'events', order: 0 },
            label,
            data: values,
            days: BUCKETS,
            labels: BUCKETS,
            count: values.reduce((sum, value) => sum + value, 0),
        },
    ],
})

const breakdownTable = (rows: (string | number)[][]): Record<string, unknown> => ({
    columns: ['context.columns.breakdown_value', 'context.columns.visitors'],
    results: rows,
})

const handlers = (
    overviewHuman: Record<string, unknown>,
    overviewCrawler: Record<string, unknown>,
    leaderboard: Record<string, unknown> = LEADERBOARD,
    // The AI sections read their own queries, so an empty overview has to empty those too.
    hasAiData: boolean = true
): Parameters<typeof mswDecorator>[0] => ({
    get: {
        '/stats': () => [200, { users_on_product: 2387 }],
        '/api/projects/:team_id/event_definitions': () => [200, { count: 5 }],
    },
    post: {
        '/api/environments/:team_id/query/:kind': async ({ request }) => {
            const query = ((await request.json()) as any).query
            const source = query.source ?? query
            const kind = source.kind

            if (kind === 'DatabaseSchemaQuery') {
                return [200, { tables: {}, joins: [] }]
            }
            if (kind === 'TrendsQuery') {
                return [200, hasAiData ? trend('Visitors', [180, 220, 190, 260, 240, 310, 295]) : { results: [] }]
            }
            if (kind === 'WebBotsTableQuery') {
                return [
                    200,
                    breakdownTable(
                        hasAiData
                            ? [
                                  ['GPTBot', 31200],
                                  ['ClaudeBot', 24800],
                                  ['PerplexityBot', 16400],
                                  ['Google-Extended', 9700],
                              ]
                            : []
                    ),
                ]
            }
            if (kind === 'WebStatsTableQuery') {
                if (source.breakdownBy === 'InitialReferringDomain') {
                    return [
                        200,
                        breakdownTable(
                            hasAiData
                                ? [
                                      ['chatgpt.com', 640],
                                      ['perplexity.ai', 410],
                                      ['claude.ai', 220],
                                  ]
                                : []
                        ),
                    ]
                }
                return [200, CANDIDATES]
            }
            if (kind === 'HogQLQuery') {
                if (source.query?.includes('AS crawls')) {
                    return [200, overviewCrawler]
                }
                if (source.query?.includes('AS visitors')) {
                    return [200, overviewHuman]
                }
                return [200, leaderboard]
            }
        },
    },
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Web Analytics/Search & AI',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.webAnalyticsPagePerformance(),
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE],
        testOptions: {
            includeNavigationInSnapshot: true,
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [mswDecorator(handlers(OVERVIEW_HUMAN, OVERVIEW_CRAWLER))],
}
export default meta

WebAnalyticsPagePerformanceNoAiTraffic.decorators = [
    mswDecorator(handlers(OVERVIEW_HUMAN_NO_AI, OVERVIEW_CRAWLER_NONE, LEADERBOARD_NO_AI, false)),
]
export function WebAnalyticsPagePerformanceNoAiTraffic(): JSX.Element {
    return <App />
}

export function WebAnalyticsPagePerformance(): JSX.Element {
    const { setConversionGoal } = useActions(webAnalyticsLogic)

    useEffect(() => {
        setConversionGoal({ customEventName: 'signed_up' })
    }, [setConversionGoal])

    return <App />
}
