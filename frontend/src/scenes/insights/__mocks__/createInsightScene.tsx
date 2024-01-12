import { StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'

import { setFeatureFlags, useStorybookMocks } from '~/mocks/browser'
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
                    ctx.delay(100),
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
        })
        setFeatureFlags([FEATURE_FLAGS.RETENTION_BREAKDOWN])

        useEffect(() => {
            router.actions.push(`/insights/${insight.short_id}${count}${mode === 'edit' ? '/edit' : ''}`)
        }, [])

        return <App />
    }
}
