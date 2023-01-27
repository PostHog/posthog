import { ComponentMeta, ComponentStory } from '@storybook/react'
import { QueryRunner } from '~/queries/QueryRunner/QueryRunner'
import { examples } from '~/queries/examples'
import { mswDecorator } from '~/mocks/browser'
import events from './__mocks__/EventsNode.json'
import persons from './__mocks__/PersonsNode.json'

export default {
    title: 'Queries/DataNode',
    component: QueryRunner,
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
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
} as ComponentMeta<typeof QueryRunner>

const QueryTemplate: ComponentStory<typeof QueryRunner> = QueryRunner

export const Events = QueryTemplate.bind({})
Events.args = { query: examples['Events'] }

export const Persons = QueryTemplate.bind({})
Persons.args = { query: examples['Persons'] }
