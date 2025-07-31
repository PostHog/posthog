import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { Query } from '~/queries/Query/Query'
import { examples } from '~/queries/examples'

import webVitalsPathBreakdown from './__mocks__/WebVitalsPathBreakdown.json'

type Story = StoryObj<typeof Query>
const meta: Meta<typeof Query> = {
    title: 'Queries/WebVitalsPathBreakdown',
    component: Query,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': (req) => {
                    if ((req.body as any).query.kind === 'WebVitalsPathBreakdownQuery') {
                        return [200, webVitalsPathBreakdown]
                    }
                },
            },
        }),
    ],
}
export default meta

const QueryTemplate: StoryFn<typeof Query> = (args) => <Query {...args} />

export const WebVitalsPathBreakdown: Story = QueryTemplate.bind({})
WebVitalsPathBreakdown.args = { query: examples['WebVitalsPathBreakdown'] }
