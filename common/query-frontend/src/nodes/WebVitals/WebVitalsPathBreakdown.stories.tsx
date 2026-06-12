import type { Meta, StoryObj } from '@storybook/react'

import { examples } from '@posthog/query-frontend/examples'
import { Query, QueryProps } from '@posthog/query-frontend/Query/Query'
import { Node } from '@posthog/query-frontend/schema/schema-general'

import { mswDecorator } from '~/mocks/browser'

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
                '/api/environments/:team_id/query/:kind/': (req) => {
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
