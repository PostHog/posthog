import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Query } from '~/queries/Query/Query'
import { examples } from './DataTable.examples'
import { mswDecorator } from '~/mocks/browser'
import events from '../DataNode/__mocks__/EventsNode.json'
import persons from '../DataNode/__mocks__/PersonsNode.json'

export default {
    title: 'Queries/DataTable',
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

export const AllDefaults = QueryTemplate.bind({})
AllDefaults.args = { query: examples['AllDefaults'] }

export const Minimalist = QueryTemplate.bind({})
Minimalist.args = { query: examples['Minimalist'] }

export const ManyColumns = QueryTemplate.bind({})
ManyColumns.args = { query: examples['ManyColumns'] }

export const ShowFilters = QueryTemplate.bind({})
ShowFilters.args = { query: examples['ShowFilters'] }

export const ShowTools = QueryTemplate.bind({})
ShowTools.args = { query: examples['ShowTools'] }

export const ShowAllTheThings = QueryTemplate.bind({})
ShowAllTheThings.args = { query: examples['ShowAllTheThings'] }

export const Persons = QueryTemplate.bind({})
Persons.args = { query: examples['Persons'] }

export const PersonsTable = QueryTemplate.bind({})
PersonsTable.args = { query: examples['PersonsTable'] }
