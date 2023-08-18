import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { Query } from '~/queries/Query/Query'
import { examples } from './DataTable.examples'
import { mswDecorator } from '~/mocks/browser'
import events from '../DataNode/__mocks__/EventsNode.json'
import persons from '../DataNode/__mocks__/PersonsNode.json'

type Story = StoryObj<typeof Query>
const meta: Meta<typeof Query> = {
    title: 'Queries/DataTable',
    component: Query,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: { skip: true },
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

export const AllDefaults: Story = {
    render: QueryTemplate,
    args: { query: examples['AllDefaults'] },
}

export const Minimalist: Story = {
    render: QueryTemplate,
    args: { query: examples['Minimalist'] },
}

export const ManyColumns: Story = {
    render: QueryTemplate,
    args: { query: examples['ManyColumns'] },
}

export const ShowFilters: Story = {
    render: QueryTemplate,
    args: { query: examples['ShowFilters'] },
}

export const ShowTools: Story = {
    render: QueryTemplate,
    args: { query: examples['ShowTools'] },
}

export const ShowAllTheThings: Story = {
    render: QueryTemplate,
    args: { query: examples['ShowAllTheThings'] },
}

export const Persons: Story = {
    render: QueryTemplate,
    args: { query: examples['Persons'] },
}

export const PersonsTable: Story = {
    render: QueryTemplate,
    args: { query: examples['PersonsTable'] },
}
