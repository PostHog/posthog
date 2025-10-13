import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { App } from 'scenes/App'

import { useOnMountEffect } from '~/lib/hooks/useOnMountEffect'
import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

let shortCounter = 0
function createSQLInsightStory(insight: any, mode: 'view' | 'edit' = 'view'): StoryFn<typeof App> {
    const count = shortCounter++
    return function SQLInsightStory() {
        document.body.classList.add('storybook-test-runner')

        useStorybookMocks({
            get: {
                '/api/environments/:team_id/insights/': (_, __, ctx) => [
                    ctx.status(200),
                    ctx.json({
                        count: 1,
                        results: [
                            {
                                ...insight,
                                short_id: `${insight.short_id}${count}`,
                                id: (insight.id ?? 0) + 1 + count,
                            },
                        ],
                    }),
                ],
            },
            post: {
                '/api/environments/:team_id/query/': (req, __, ctx) => [
                    ctx.status(200),
                    ctx.json({
                        cache_key: req.params.query,
                        calculation_trigger: null,
                        error: '',
                        hasMore: false,
                        is_cached: true,
                        query_status: null,
                        results: insight.result,
                        columns: insight.columns,
                        types: insight.types,
                    }),
                ],
            },
        })

        useOnMountEffect(() => {
            router.actions.push(`/insights/${insight.short_id}${count}${mode === 'edit' ? '/edit' : ''}`)
        })

        return <App />
    }
}

type Story = StoryObj<typeof App>
const meta: Meta = {
    title: 'Scenes-App/Insights/SQL',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            viewport: {
                // needs a slightly larger width to push the rendered scene away from breakpoint boundary
                width: 1300,
                height: 720,
            },
        },
        viewMode: 'story',
        mockDate: '2022-03-11',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/persons/retention': sampleRetentionPeopleResponse,
                '/api/environments/:team_id/persons/properties': samplePersonProperties,
                '/api/projects/:team_id/groups_types': [],
            },
            post: {
                '/api/projects/:team_id/cohorts/': { id: 1 },
            },
        }),
    ],
}
export default meta
/* eslint-disable @typescript-eslint/no-var-requires */
// SQL (HogQL) Insights
export const SQLTable: Story = createSQLInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json')
)
SQLTable.parameters = { testOptions: { waitForSelector: '.DataVisualization table' } }

export const SQLTableEdit: Story = createSQLInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json'),
    'edit'
)
SQLTableEdit.parameters = { testOptions: { waitForSelector: '.DataVisualization table' } }

export const SQLQueryError: StoryFn = () => {
    document.body.classList.add('storybook-test-runner')

    const insight = require('../../../mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json')

    useStorybookMocks({
        get: {
            '/api/environments/:team_id/insights/': (_, __, ctx) => [
                ctx.status(200),
                ctx.json({
                    count: 1,
                    results: [
                        {
                            ...insight,
                            short_id: `${insight.short_id}error`,
                            id: (insight.id ?? 0) + 1000,
                        },
                    ],
                }),
            ],
        },
        post: {
            '/api/environments/:team_id/query/': (_, __, ctx) => [
                ctx.delay(100),
                ctx.status(500),
                ctx.json({
                    error: 'Query execution failed: Syntax error in SQL query at line 5',
                    type: 'query_error',
                }),
            ],
        },
    })

    useOnMountEffect(() => {
        router.actions.push(`/insights/${insight.short_id}error`)
    })

    return <App />
}
SQLQueryError.parameters = {
    testOptions: {
        waitForSelector: '.InsightErrorState',
    },
}
/* eslint-enable @typescript-eslint/no-var-requires */
