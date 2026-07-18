import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { examples } from '~/queries/examples'
import { Query, QueryProps } from '~/queries/Query/Query'
import { Node } from '~/queries/schema/schema-general'

import webVitals from './__mocks__/WebVitals.json'
import webVitalsTrends from './__mocks__/WebVitalsTrends.json'

type Story = StoryObj<QueryProps<Node>>
const meta: Meta<QueryProps<Node>> = {
    title: 'Queries/WebVitals',
    component: Query,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: {
            waitForLoadersToDisappear: true,
            waitForSelector: '[data-attr=trend-line-graph] > canvas',
        },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const body = (await request.json()) as any
                    if (body.query.kind === 'WebVitalsQuery') {
                        return [200, webVitals]
                    } else if (body.query.kind === 'TrendsQuery') {
                        return [200, webVitalsTrends]
                    }
                },
            },
        }),
    ],
    // NOTE: See InsightCard.scss to see why we need this wrapper
    render: (args) => {
        return (
            <div className="WebAnalyticsDashboard">
                <div className="InsightVizDisplay">
                    <Query {...args} />
                </div>
            </div>
        )
    },
}
export default meta

export const WebVitals: Story = {
    args: { query: examples['WebVitals'] },
}

// The active metric has no data at the selected percentile/filters — the graph shows an explicit
// empty state instead of a blank line.
export const WebVitalsNoData: Story = {
    args: { query: examples['WebVitals'] },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: true,
            waitForSelector: '[data-attr=web-vitals-graph-empty]',
        },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const body = (await request.json()) as any
                    if (body.query.kind === 'WebVitalsQuery') {
                        return [200, { ...webVitals, results: [] }]
                    } else if (body.query.kind === 'TrendsQuery') {
                        return [200, webVitalsTrends]
                    }
                },
            },
        }),
    ],
}
