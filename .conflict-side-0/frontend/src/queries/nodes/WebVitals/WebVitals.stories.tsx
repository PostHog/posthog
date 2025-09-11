import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { Query } from '~/queries/Query/Query'
import { examples } from '~/queries/examples'

import webVitals from './__mocks__/WebVitals.json'
import webVitalsTrends from './__mocks__/WebVitalsTrends.json'

type Story = StoryObj<typeof Query>
const meta: Meta<typeof Query> = {
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
                '/api/environments/:team_id/query/': (req) => {
                    if ((req.body as any).query.kind === 'WebVitalsQuery') {
                        return [200, webVitals]
                    } else if ((req.body as any).query.kind === 'TrendsQuery') {
                        return [200, webVitalsTrends]
                    }
                },
            },
        }),
    ],
}
export default meta

// NOTE: See InsightCard.scss to see why we need this wrapper
const QueryTemplate: StoryFn<typeof Query> = (args) => {
    return (
        <div className="WebAnalyticsDashboard">
            <div className="InsightVizDisplay">
                <Query {...args} />
            </div>
        </div>
    )
}

export const WebVitals: Story = QueryTemplate.bind({})
WebVitals.args = { query: examples['WebVitals'] }
