import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { Query } from '~/queries/Query/Query'

import events from '../DataNode/__mocks__/EventsNode.json'
import persons from '../DataNode/__mocks__/PersonsNode.json'
import { examples } from './DataTable.examples'

type Story = StoryObj<typeof Query>
const meta: Meta<typeof Query> = {
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
            post: {
                '/api/environments/:team_id/query/': (req, __, ctx) => [
                    ctx.status(200),
                    ctx.json({
                        cache_key: req.params.query,
                        calculation_trigger: null,
                        error: '',
                        hasMore: false,
                        is_cached: true,
                        query_status: null,
                        results: [],
                    }),
                ],
            },
        }),
    ],
}
export default meta

const QueryTemplate: StoryFn<typeof Query> = (args) => <Query {...args} context={{ showQueryEditor: true }} />

export const AllDefaults: Story = QueryTemplate.bind({})
AllDefaults.args = { query: examples['AllDefaults'] }

export const Minimalist: Story = QueryTemplate.bind({})
Minimalist.args = { query: examples['Minimalist'] }

export const ManyColumns: Story = QueryTemplate.bind({})
ManyColumns.args = { query: examples['ManyColumns'] }

export const ShowFilters: Story = QueryTemplate.bind({})
ShowFilters.args = { query: examples['ShowFilters'] }

export const ShowTools: Story = QueryTemplate.bind({})
ShowTools.args = { query: examples['ShowTools'] }

export const ShowAllTheThings: Story = QueryTemplate.bind({})
ShowAllTheThings.args = { query: examples['ShowAllTheThings'] }

export const Persons: Story = QueryTemplate.bind({})
Persons.args = { query: examples['Persons'] }

export const PersonsTable: Story = QueryTemplate.bind({})
PersonsTable.args = { query: examples['PersonsTable'] }

export const MarketingAnalyticsTablePinnedColumns: Story = QueryTemplate.bind({})
MarketingAnalyticsTablePinnedColumns.args = { query: examples['MarketingAnalyticsTablePinnedColumns'] }
