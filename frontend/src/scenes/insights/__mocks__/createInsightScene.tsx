import { InsightModel } from '~/types'
import { useStorybookMocks } from '~/mocks/browser'
import React, { useEffect } from 'react'
import { router } from 'kea-router'
import { App } from 'scenes/App'

let shortCounter = 0
export function createInsightScene(insight: Partial<InsightModel>): () => JSX.Element {
    const count = shortCounter++
    return function InsightStorybookScene() {
        useStorybookMocks({
            get: {
                '/api/projects/:projectId/insights/': (_, __, ctx) => [
                    ctx.delay(100),
                    ctx.status(200),
                    ctx.json({
                        count: 1,
                        results: [
                            { ...insight, short_id: `${insight.short_id}${count}`, id: (insight.id ?? 0) + 1 + count },
                        ],
                    }),
                ],
            },
        })

        useEffect(() => {
            router.actions.push(`/insights/${insight.short_id}${count}`)
        }, [])

        return <App />
    }
}
