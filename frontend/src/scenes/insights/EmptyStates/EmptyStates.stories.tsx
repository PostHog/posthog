import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { useStorybookMocks } from '~/mocks/browser'
import { InsightShortId } from '~/types'

import insight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import { insightVizDataLogic } from '../insightVizDataLogic'
import funnelOneStep from './funnelOneStep.json'

type Story = StoryObj<typeof App>
const meta: Meta = {
    component: App,
    title: 'Scenes-App/Insights/Error & Empty States',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: `/insights/${insight.short_id}`,
        testOptions: {
            waitForSelector: '[data-attr="insight-empty-state"]',
        },
    },
}
export default meta

export const Empty: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/insights/': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(200),
                ctx.json({ count: 1, results: [{ ...insight, result: [] }] }),
            ],
        },
    })

    return <App />
}

export const ServerError: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/insights/': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(200),
                ctx.json({ count: 1, results: [{ ...insight, result: null }] }),
            ],
            '/api/environments/:team_id/insights/:id': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(500),
                ctx.json({
                    type: 'server_error',
                    detail: 'There is nothing you can do to stop the impending catastrophe.',
                }),
            ],
        },
    })

    return <App />
}

export const QueryServerError: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/insights/': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(200),
                ctx.json({
                    count: 1,
                    results: [insight],
                }),
            ],
        },
        post: {
            '/api/environments/:team_id/query/': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(500),
                ctx.json({
                    type: 'server_error',
                    detail: 'There is nothing you can do to stop the impending catastrophe.',
                }),
            ],
        },
    })

    return <App />
}
QueryServerError.parameters = {
    testOptions: {
        waitForSelector: '[data-attr="insight-retry-button"]',
    },
}

export const ValidationError: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/insights/': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(200),
                ctx.json({ count: 1, results: [{ ...insight, result: null }] }),
            ],
        },
        post: {
            '/api/environments/:team_id/insights/:id': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(400),
                ctx.json({
                    type: 'validation_error',
                    detail: 'You forgot to hug the person next to you. Please do that now.',
                }),
            ],
        },
    })

    return <App />
}

export const EstimatedQueryExecutionTimeTooLong: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/insights/': (_, __, ctx) => [
                ctx.status(200),
                ctx.json({ count: 1, results: [{ ...insight, result: null }] }),
            ],
        },
        post: {
            '/api/environments/:team_id/query/': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(512),
                ctx.json({
                    type: 'server_error',
                    detail: 'Estimated query execution time is too long. Try reducing its scope by changing the time range.',
                }),
            ],
        },
    })

    return <App />
}
EstimatedQueryExecutionTimeTooLong.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
        waitForSelector: '[data-attr=insight-loading-too-long]',
    },
}

export const LongLoading: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/insights/': (_, __, ctx) => [
                ctx.status(200),
                ctx.json({ count: 1, results: [{ ...insight, result: null }] }),
            ],
        },
        post: {
            '/api/environments/:team_id/query/': (_, __, ctx) => [ctx.delay('infinite')],
        },
    })

    useDelayedOnMountEffect(() => {
        const logic = insightVizDataLogic.findMounted({ dashboardItemId: insight.short_id as InsightShortId })
        logic?.actions.setTimedOutQueryId('a-uuid-query-id') // Show the suggestions immediately
    })

    return <App />
}
LongLoading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
        waitForSelector: '[data-attr=insight-loading-waiting-message]',
    },
}

export const FunnelSingleStep: Story = createInsightStory(funnelOneStep as any)
