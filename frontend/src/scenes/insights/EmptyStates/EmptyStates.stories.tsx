import { useEffect } from 'react'
import { Meta } from '@storybook/react'
import funnelOneStep from './funnelOneStep.json'
import { useStorybookMocks } from '~/mocks/browser'
import { router } from 'kea-router'
import insight from '../__mocks__/trendsLine.json'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId } from '~/types'
import { createInsightScene } from 'scenes/insights/__mocks__/createInsightScene'
import { App } from 'scenes/App'

// some metadata and optional parameters
export default {
    title: 'Scenes-App/Insights/Error states',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
} as Meta

export function EmptyState(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/insights/': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(200),
                ctx.json({ count: 1, results: [{ ...insight, result: [] }] }),
            ],
        },
    })
    useEffect(() => {
        router.actions.push(`/insights/${insight.short_id}`)
    }, [])
    return <App />
}

export function ErrorState(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/insights/': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(200),
                ctx.json({ count: 1, results: [{ ...insight, result: null }] }),
            ],
            '/api/projects/:team_id/insights/:id': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(500),
                ctx.json({ detail: 'a fake error' }),
            ],
        },
    })
    useEffect(() => {
        router.actions.push(`/insights/${insight.short_id}`)
    }, [])
    return <App />
}

export function TimeoutState(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/insights/': (_, __, ctx) => [
                ctx.status(200),
                ctx.json({ count: 1, results: [{ ...insight, result: null }] }),
            ],
            '/api/projects/:team_id/insights/trend/': (_, __, ctx) => [
                ctx.delay(86400000),
                ctx.status(200),
                ctx.json({ result: insight.result }),
            ],
            '/api/projects/:team_id/insights/:id': (_, __, ctx) => [
                ctx.delay(86400000),
                ctx.status(200),
                ctx.json({ result: insight.result }),
            ],
        },
    })
    useEffect(() => {
        router.actions.push(`/insights/${insight.short_id}`)
        window.setTimeout(() => {
            const logic = insightLogic.findMounted({ dashboardItemId: insight.short_id as InsightShortId })
            logic?.actions.markInsightTimedOut('a-uuid-query-id')
        }, 50)
    }, [])
    return <App />
}

export const FunnelSingleStep = createInsightScene(funnelOneStep as any)
