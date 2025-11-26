import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { IconChevronRight, IconTrash } from '@posthog/icons'

import { LemonMenuItem, LemonMenuItems, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'
import { IconLink } from 'lib/lemon-ui/icons'

import { mswDecorator } from '~/mocks/browser'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { CellActionProps, QueryContext, RowActionProps } from '~/queries/types'

import events from '../DataNode/__mocks__/EventsNode.json'
import persons from '../DataNode/__mocks__/PersonsNode.json'
import { examples } from './DataTable.examples'
import { QueryFeature } from './queryFeatures'

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

export const PinnedColumnsAtTheBeginning: Story = QueryTemplate.bind({})
PinnedColumnsAtTheBeginning.args = {
    query: examples['PinnedColumnsAtTheBeginning'],
}

export const PinnedColumnsInTheMiddle: Story = QueryTemplate.bind({})
PinnedColumnsInTheMiddle.args = {
    query: examples['PinnedColumnsInTheMiddle'],
}

// Static mock data for cell/row actions stories - HogQL query response format
const mockHogQLResults = {
    columns: ['event', 'person', 'timestamp', 'properties.$browser'],
    hasMore: false,
    results: [
        ['$pageview', 'user@example.com', '2024-01-15T10:30:00Z', 'Chrome'],
        ['button_clicked', 'alice@company.io', '2024-01-15T10:28:00Z', 'Firefox'],
        ['form_submitted', 'bob@startup.co', '2024-01-15T10:25:00Z', 'Safari'],
        ['$autocapture', 'carol@enterprise.com', '2024-01-15T10:22:00Z', 'Chrome'],
        ['purchase_completed', 'dave@shop.net', '2024-01-15T10:20:00Z', 'Edge'],
        ['$pageview', 'eve@agency.io', '2024-01-15T10:18:00Z', 'Chrome'],
        ['signup_started', 'frank@tech.co', '2024-01-15T10:15:00Z', 'Firefox'],
        ['feature_used', 'grace@design.com', '2024-01-15T10:12:00Z', 'Safari'],
    ],
    types: ['String', 'String', 'DateTime', 'String'],
}

const hogQLQuery: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: 'SELECT event, person.properties.email as person, timestamp, properties.$browser FROM events LIMIT 10',
    },
    columns: ['event', 'person', 'timestamp', 'properties.$browser'],
}

// Cell Actions - demonstrates custom cell action menus for specific columns
const CellActionsContext: QueryContext = {
    showQueryEditor: false,
    extraDataTableQueryFeatures: [QueryFeature.cellActions],
    columns: {
        event: {
            cellActions: ({ value }: CellActionProps) => {
                const eventName = String(value || '')
                const menuItems: LemonMenuItems = [
                    {
                        title: `"${eventName.length > 20 ? eventName.slice(0, 20) + '...' : eventName}"`,
                        items: [
                            {
                                label: 'Actions',
                                icon: <IconLink />,
                                sideIcon: <IconChevronRight />,
                                items: [
                                    {
                                        label: 'Filter to this event',
                                        onClick: () => alert(`Filtering to ${eventName}`),
                                    },
                                    {
                                        label: 'Exclude this event',
                                        icon: <IconTrash />,
                                        status: 'danger' as const,
                                        onClick: () => alert(`Excluding ${eventName}`),
                                    },
                                ] as LemonMenuItem[],
                            },
                        ],
                    },
                ]
                return <LemonMenuOverlay items={menuItems} />
            },
        },
    },
}

const CellActionsTemplate: StoryFn<typeof Query> = (args) => (
    <Query {...args} context={CellActionsContext} cachedResults={mockHogQLResults} />
)

export const WithCellActions: Story = CellActionsTemplate.bind({})
WithCellActions.args = { query: hogQLQuery }
WithCellActions.parameters = {
    docs: {
        description: {
            story: 'DataTable with custom cell actions on the "event" column. Hover over a cell in the event column to see the action menu icon appear.',
        },
    },
}

// Row Actions - demonstrates custom row action menus at the end of each row
const RowActionsContext: QueryContext = {
    showQueryEditor: false,
    extraDataTableQueryFeatures: [QueryFeature.rowActions],
    rowActions: ({ record }: RowActionProps) => {
        const eventValue = Array.isArray(record.result) ? String(record.result[0] || '') : ''
        const personValue = Array.isArray(record.result) ? String(record.result[1] || '') : ''
        const menuItems: LemonMenuItems = [
            {
                title: 'Row Actions',
                items: [
                    {
                        label: `Event: "${eventValue.length > 15 ? eventValue.slice(0, 15) + '...' : eventValue}"`,
                        icon: <IconLink />,
                        sideIcon: <IconChevronRight />,
                        items: [
                            {
                                label: 'View event details',
                                onClick: () => alert(`Viewing details for ${eventValue}`),
                            },
                            {
                                label: 'Create action from event',
                                onClick: () => alert(`Creating action from ${eventValue}`),
                            },
                        ] as LemonMenuItem[],
                    },
                    {
                        label: `View ${personValue}'s sessions`,
                        onClick: () => alert(`Opening session recordings for ${personValue}`),
                    },
                    {
                        label: 'Export row',
                        onClick: () => alert('Exporting row data'),
                    },
                ] as LemonMenuItem[],
            },
        ]
        return <LemonMenuOverlay items={menuItems} />
    },
}

const RowActionsTemplate: StoryFn<typeof Query> = (args) => (
    <Query {...args} context={RowActionsContext} cachedResults={mockHogQLResults} />
)

export const WithRowActions: Story = RowActionsTemplate.bind({})
WithRowActions.args = { query: hogQLQuery }
WithRowActions.parameters = {
    docs: {
        description: {
            story: 'DataTable with custom row actions. A three-dot menu appears at the end of each row when you hover over it.',
        },
    },
}

// Combined Cell Actions and Row Actions
const CombinedActionsContext: QueryContext = {
    showQueryEditor: false,
    extraDataTableQueryFeatures: [QueryFeature.cellActions, QueryFeature.rowActions],
    columns: {
        event: {
            cellActions: ({ value }: CellActionProps) => {
                const eventName = String(value || '')
                const menuItems: LemonMenuItems = [
                    {
                        title: `"${eventName.length > 20 ? eventName.slice(0, 20) + '...' : eventName}"`,
                        items: [
                            {
                                label: 'Event Actions',
                                icon: <IconLink />,
                                sideIcon: <IconChevronRight />,
                                items: [
                                    {
                                        label: 'Filter to this event',
                                        onClick: () => alert(`Filtering to ${eventName}`),
                                    },
                                    {
                                        label: 'Exclude this event',
                                        icon: <IconTrash />,
                                        status: 'danger' as const,
                                        onClick: () => alert(`Excluding ${eventName}`),
                                    },
                                ] as LemonMenuItem[],
                            },
                        ],
                    },
                ]
                return <LemonMenuOverlay items={menuItems} />
            },
        },
        person: {
            cellActions: ({ value }: CellActionProps) => {
                const personDisplay = String(value || 'Unknown')
                const menuItems: LemonMenuItems = [
                    {
                        title: `"${personDisplay.length > 15 ? personDisplay.slice(0, 15) + '...' : personDisplay}"`,
                        items: [
                            {
                                label: 'Person Actions',
                                icon: <IconLink />,
                                sideIcon: <IconChevronRight />,
                                items: [
                                    {
                                        label: 'View person profile',
                                        onClick: () => alert(`Viewing profile for ${personDisplay}`),
                                    },
                                    {
                                        label: 'View recordings',
                                        onClick: () => alert(`Viewing recordings for ${personDisplay}`),
                                    },
                                ] as LemonMenuItem[],
                            },
                        ],
                    },
                ]
                return <LemonMenuOverlay items={menuItems} />
            },
        },
        // Cell actions on the LAST column to test interaction with row actions
        'properties.$browser': {
            cellActions: ({ value }: CellActionProps) => {
                const browser = String(value || 'Unknown')
                const menuItems: LemonMenuItems = [
                    {
                        title: `Browser: "${browser}"`,
                        items: [
                            {
                                label: 'Browser Actions',
                                icon: <IconLink />,
                                sideIcon: <IconChevronRight />,
                                items: [
                                    {
                                        label: `Filter to ${browser} users`,
                                        onClick: () => alert(`Filtering to ${browser} users`),
                                    },
                                    {
                                        label: `Exclude ${browser}`,
                                        icon: <IconTrash />,
                                        status: 'danger' as const,
                                        onClick: () => alert(`Excluding ${browser} users`),
                                    },
                                ] as LemonMenuItem[],
                            },
                        ],
                    },
                ]
                return <LemonMenuOverlay items={menuItems} />
            },
        },
    },
    rowActions: ({ record }: RowActionProps) => {
        const eventValue = Array.isArray(record.result) ? String(record.result[0] || '') : ''
        const menuItems: LemonMenuItems = [
            {
                title: 'Row Actions',
                items: [
                    {
                        label: 'View full event details',
                        onClick: () => alert(`Viewing full details for event row`),
                    },
                    {
                        label: 'Copy event JSON',
                        onClick: () => alert(`Copying JSON for ${eventValue}`),
                    },
                ] as LemonMenuItem[],
            },
        ]
        return <LemonMenuOverlay items={menuItems} />
    },
}

const CombinedActionsTemplate: StoryFn<typeof Query> = (args) => (
    <Query {...args} context={CombinedActionsContext} cachedResults={mockHogQLResults} />
)

export const WithCellAndRowActions: Story = CombinedActionsTemplate.bind({})
WithCellAndRowActions.args = { query: hogQLQuery }
WithCellAndRowActions.parameters = {
    docs: {
        description: {
            story: 'DataTable with both cell actions (on event, person, AND the last browser column) and row actions. This demonstrates how cell actions on the last column interact with row actions.',
        },
    },
}
