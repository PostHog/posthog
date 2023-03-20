import { ComponentMeta, ComponentStory } from '@storybook/react'
import { examples } from '~/queries/examples'
import { mswDecorator } from '~/mocks/browser'
import events from './__mocks__/EventsNode.json'
import persons from './__mocks__/PersonsNode.json'
import { Query } from '~/queries/Query/Query'

export default {
    title: 'Queries/DataNode',
    component: Query,
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
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
} as ComponentMeta<typeof Query>

const QueryTemplate: ComponentStory<typeof Query> = (args) => <Query {...args} context={{ showQueryEditor: true }} />

export const Events = QueryTemplate.bind({})
Events.args = { query: examples['Events'] }

export const Persons = QueryTemplate.bind({})
Persons.args = { query: examples['Persons'] }
