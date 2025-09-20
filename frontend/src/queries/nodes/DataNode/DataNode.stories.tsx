import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { Query } from '~/queries/Query/Query'
import { examples } from '~/queries/examples'

import events from './__mocks__/EventsNode.json'
import persons from './__mocks__/PersonsNode.json'

type Story = StoryObj<typeof Query>
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
}
export default meta

const QueryTemplate: StoryFn<typeof Query> = (args) => <Query {...args} context={{ showQueryEditor: true }} />

export const Events: Story = QueryTemplate.bind({})
Events.args = { query: examples['Events'] }

export const Persons: Story = QueryTemplate.bind({})
Persons.args = { query: examples['Persons'] }
