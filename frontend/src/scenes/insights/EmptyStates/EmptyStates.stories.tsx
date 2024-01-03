import { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { useStorybookMocks } from '~/mocks/browser'
import { InsightShortId } from '~/types'

import insight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import { insightVizDataLogic } from '../insightVizDataLogic'
import funnelOneStep from './funnelOneStep.json'

type Story = StoryObj<typeof App>
const meta: Meta = {
    title: 'Scenes-App/Insights/Error states',
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta
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
        },
    })
    useEffect(() => {
        router.actions.push(`/insights/${insight.short_id}`)
        window.setTimeout(() => {
            const logic = insightVizDataLogic.findMounted({ dashboardItemId: insight.short_id as InsightShortId })
            logic?.actions.setTimedOutQueryId('a-uuid-query-id')
        }, 150)
    }, [])
    return <App />
}

export const FunnelSingleStep: Story = createInsightStory(funnelOneStep as any)
