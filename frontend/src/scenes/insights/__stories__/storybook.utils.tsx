import { InsightModel } from '~/types'
import { useStorybookMocks } from '~/mocks/browser'
import React, { useEffect } from 'react'
import { router } from 'kea-router'
import { InsightScene } from 'scenes/insights/InsightScene'

export function createInsightScene(insight: Partial<InsightModel>): () => JSX.Element {
    return function InsightStorybookScene() {
        useStorybookMocks({
            get: {
                '/api/projects/:projectId/insights/': (_, __, ctx) => [
                    ctx.delay(100),
                    ctx.status(200),
                    ctx.json({ count: 1, results: [insight] }),
                ],
            },
        })

        useEffect(() => {
            router.actions.push(`/insights/${insight.short_id}`)
        }, [])

        return <InsightScene />
    }
}
