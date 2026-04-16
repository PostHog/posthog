import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { Query, QueryProps } from '~/queries/Query/Query'
import { Node } from '~/queries/schema/schema-general'

import events from '../DataNode/__mocks__/EventsNode.json'
import persons from '../DataNode/__mocks__/PersonsNode.json'
import { examples } from './DataTable.examples'

type Story = StoryObj<QueryProps<Node>>
const meta: Meta<QueryProps<Node>> = {
    title: 'Queries/DataTable',
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

export const AllDefaults: Story = { args: { query: examples['AllDefaults'] } }

export const Minimalist: Story = { args: { query: examples['Minimalist'] } }

export const ManyColumns: Story = { args: { query: examples['ManyColumns'] } }

export const ShowFilters: Story = { args: { query: examples['ShowFilters'] } }

export const ShowTools: Story = { args: { query: examples['ShowTools'] } }

export const ShowAllTheThings: Story = { args: { query: examples['ShowAllTheThings'] } }

export const Persons: Story = { args: { query: examples['Persons'] } }

export const PersonsTable: Story = { args: { query: examples['PersonsTable'] } }

export const PinnedColumnsAtTheBeginning: Story = {
    args: { query: examples['PinnedColumnsAtTheBeginning'] },
}

export const PinnedColumnsInTheMiddle: Story = {
    args: { query: examples['PinnedColumnsInTheMiddle'] },
}
