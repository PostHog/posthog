// EmptyStates.stories.tsx
import React, { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { InsightScene } from '../InsightScene'
import funnelOneStep from './funnelOneStep.json'
import { useStorybookMocks } from '~/mocks/browser'
import { router } from 'kea-router'
import insight from '../__mocks__/trendsLine.json'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId } from '~/types'
import { createInsightScene } from 'scenes/insights/__mocks__/createInsightScene'

// some metadata and optional parameters
export default {
    title: 'Scenes/Insights/Error states',
    parameters: { options: { showPanel: false }, viewMode: 'canvas' },
} as Meta

export function EmptyState(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:projectId/insights/': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(200),
                ctx.json({ count: 1, results: [{ ...insight, result: [] }] }),
            ],
        },
    })
    useEffect(() => {
        router.actions.push(`/insights/${insight.short_id}`)
    }, [])
    return <InsightScene />
}

export function ErrorState(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:projectId/insights/': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(200),
                ctx.json({ count: 1, results: [{ ...insight, result: null }] }),
            ],
        },
    })
    useEffect(() => {
        router.actions.push(`/insights/${insight.short_id}`)
    }, [])
    return <InsightScene />
}

export function TimeoutState(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:projectId/insights/': (_, __, ctx) => [
                ctx.status(200),
                ctx.json({ count: 1, results: [{ ...insight, result: null }] }),
            ],
            '/api/projects/1/insights/trend/': (_, __, ctx) => [
                ctx.delay(86400000),
                ctx.status(200),
                ctx.json({ result: insight.result }),
            ],
        },
    })
    useEffect(() => {
        router.actions.push(`/insights/${insight.short_id}`)
        window.setTimeout(() => {
            const logic = insightLogic({ dashboardItemId: insight.short_id as InsightShortId })
            logic.actions.setShowTimeoutMessage(true)
        }, 100)
    }, [])
    return <InsightScene />
}

export const FunelSingleStep = createInsightScene(funnelOneStep as any)
