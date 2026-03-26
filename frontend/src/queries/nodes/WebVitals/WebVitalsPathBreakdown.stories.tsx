import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { examples } from '~/queries/examples'
import { Query, QueryProps } from '~/queries/Query/Query'
import { Node } from '~/queries/schema/schema-general'

import webVitalsPathBreakdown from './__mocks__/WebVitalsPathBreakdown.json'

type Story = StoryObj<QueryProps<Node>>
const meta: Meta<QueryProps<Node>> = {
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

export const WebVitalsPathBreakdown: Story = {
    args: { query: examples['WebVitalsPathBreakdown'] },
}
