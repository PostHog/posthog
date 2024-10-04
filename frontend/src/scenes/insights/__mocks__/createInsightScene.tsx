import { StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'

import { useStorybookMocks } from '~/mocks/browser'
import { InsightModel } from '~/types'

let shortCounter = 0
export function createInsightStory(
    insight: Partial<InsightModel>,
    mode: 'view' | 'edit' = 'view',
    showLegend: boolean = false
): StoryFn<typeof App> {
    const count = shortCounter++
    return function InsightStory() {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/insights/': (_, __, ctx) => [
                    ctx.status(200),
                    ctx.json({
                        count: 1,
                        results: [
                            {
                                ...insight,
                                short_id: `${insight.short_id}${count}`,
                                id: (insight.id ?? 0) + 1 + count,
                                filters: {
                                    ...insight.filters,
                                    show_legend: showLegend,
                                },
                            },
                        ],
                    }),
                ],
            },
            post: {
                '/api/projects/:team_id/query/': (req, __, ctx) => [
                    ctx.status(200),
                    ctx.json({
                        cache_key: req.params.query,
                        calculation_trigger: null,
                        error: '',
                        hasMore: false,
                        is_cached: true,
                        query_status: null,
                        results: insight.result,
                    }),
                ],
            },
        })

        useEffect(() => {
            router.actions.push(`/insights/${insight.short_id}${count}${mode === 'edit' ? '/edit' : ''}`)
        }, [])

        return <App />
    }
}
