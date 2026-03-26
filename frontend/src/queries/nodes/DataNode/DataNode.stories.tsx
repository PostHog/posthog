import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { examples } from '~/queries/examples'
import { Query } from '~/queries/Query/Query'

import events from './__mocks__/EventsNode.json'
import persons from './__mocks__/PersonsNode.json'

type Story = StoryObj<typeof meta>
const meta: Meta<typeof Query> = {
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
