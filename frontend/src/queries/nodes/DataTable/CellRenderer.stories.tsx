import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'
import { NodeKind } from '~/queries/schema/schema-general'

import { examples } from './DataTable.examples'
import { Link } from '@posthog/lemon-ui'

const columns = [
    'event',
    'timestamp',
    'properties.$browser',
    'properties.$current_url',
    'person.properties.email',
    'properties.$is_authenticated',
    'properties.$is_first_visit',
]

const results = [
    [
        'pageview',
        '2022-12-04T00:57:53.072000+00:00',
        'Chrome',
        'http://localhost:8000/events',
        1800.12,
        'jb@test.com',
        true,
    ],
    [
        'pageview',
        '2022-12-04T00:57:51.500000+00:00',
        { 0: 'Safari', 1: 'Firefox' },
        'https://www.google.com/search?q=posthog',
        900010,
        'fw@test.com',
        false,
    ],
]

type Story = StoryObj<typeof Query>
const meta: Meta<typeof Query> = {
    title: 'Queries/DataTable/CellRenderer',
    component: Query,
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

const QueryTemplate: StoryFn<typeof Query> = (args) => {
    // Create cached data for the query
    const cachedData = {
        columns: columns,
        results: results,
    }

    // Create a custom query that matches our cached data columns
    const customQuery = {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.EventsQuery,
            select: columns,
        },
        showColumnConfigurator: true,
    }

    return (
        <Query
            {...args}
            query={customQuery}
            context={{ showQueryEditor: true, ...args.context }}
            cachedResults={cachedData}
        />
    )
}

const globalCellRendererContext: QueryContext = {
    cellRenderer: (value) => {
        if (value === null || value === undefined) {
            return (
                <span className="cursor-default text-muted" title="NULL">
                    —
                </span>
            )
        } else if (typeof value === 'boolean') {
            return (
                <span className={`px-2 py-1 rounded text-sm ${value ? 'bg-success-highlight' : 'bg-danger-highlight'}`}>
                    {value ? 'Yes' : 'No'}
                </span>
            )
        } else if (typeof value === 'number') {
            return <span className="font-mono text-right">{value.toLocaleString()}</span>
        } else if (typeof value === 'string' && value.startsWith('http')) {
            const domain = new URL(value).hostname
            return <Link to={value}>{domain}</Link>
        } else if (typeof value === 'string' && value.includes('@')) {
            return <Link to={`mailto:${value}`}>{value}</Link>
        } else if (typeof value === 'string' && value.includes('T')) {
            return <span> {new Date(value).toLocaleString()} </span>
        }
        return null // Let default rendering handle everything else
    },
}

export const DifferentCellReturn: Story = QueryTemplate.bind({})
DifferentCellReturn.args = {
    query: examples['ManyColumns'],
    context: globalCellRendererContext,
}
