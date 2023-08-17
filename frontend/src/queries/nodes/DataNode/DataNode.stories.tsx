import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { examples } from '~/queries/examples'
import { mswDecorator } from '~/mocks/browser'
import events from './__mocks__/EventsNode.json'
import persons from './__mocks__/PersonsNode.json'
import { Query } from '~/queries/Query/Query'

type Story = StoryObj<typeof Query>
const meta: Meta<typeof Query> = {
    title: 'Queries/DataNode',
    component: Query,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: { skip: true },
    },
    argTypes: {
        query: { defaultValue: {} },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/events': events,
                '/api/projects/:team_id/persons': persons,
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
