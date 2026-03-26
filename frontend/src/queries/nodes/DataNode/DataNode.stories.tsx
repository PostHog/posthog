import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { examples } from '~/queries/examples'
import { Query, QueryProps } from '~/queries/Query/Query'
import { Node } from '~/queries/schema/schema-general'

import events from './__mocks__/EventsNode.json'
import persons from './__mocks__/PersonsNode.json'

type Story = StoryObj<QueryProps<Node>>
const meta: Meta<QueryProps<Node>> = {
    title: 'Queries/DataNode',
    component: Query,
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/events': events,
                '/api/environments/:team_id/persons': persons,
            },
        }),
    ],
    render: (args) => <Query {...args} context={{ showQueryEditor: true }} />,
}
export default meta

export const Events: Story = {
    args: { query: examples['Events'] },
}

export const Persons: Story = {
    args: { query: examples['Persons'] },
}
