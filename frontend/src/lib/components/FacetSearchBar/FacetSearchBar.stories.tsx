import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import clsx from 'clsx'
import { useState } from 'react'

import { LemonTable } from '@posthog/lemon-ui'

import {
    ClientFacet,
    FacetSearchRows,
    FacetSearchValue,
    FacetValueOption,
    LoadFacetValues,
    ServerFacet,
    filterFacetRows,
    toFacetQuery,
} from './facetSearch'
import { FacetSearchBar } from './FacetSearchBar'

interface Ticket {
    title: string
    status: string
    priority: string
    labels: string[]
}

const capitalize = (value: string): string => value[0].toUpperCase() + value.slice(1)

const TICKET_FACETS: ClientFacet<Ticket>[] = [
    {
        key: 'status',
        label: 'Status',
        description: 'Open, pending or closed',
        showOnFocus: true,
        order: 1,
        getValues: (ticket) => [ticket.status],
        formatValue: capitalize,
    },
    {
        key: 'priority',
        label: 'Priority',
        description: 'How urgent it is',
        showOnFocus: true,
        order: 2,
        getValues: (ticket) => [ticket.priority],
        formatValue: capitalize,
    },
    {
        key: 'label',
        aliases: ['tag'],
        label: 'Label',
        description: 'Any label on the ticket',
        order: 3,
        getValues: (ticket) => ticket.labels,
    },
]

const TICKETS: FacetSearchRows<Ticket> = {
    rows: [
        { title: 'Export fails for large files', status: 'open', priority: 'high', labels: ['exports', 'bug'] },
        { title: 'Add dark mode to the editor', status: 'pending', priority: 'low', labels: ['editor'] },
        { title: 'Login link expires too soon', status: 'open', priority: 'medium', labels: ['auth', 'bug'] },
        { title: 'Rename a saved view', status: 'closed', priority: 'low', labels: ['views'] },
        { title: 'Invoice shows the wrong currency', status: 'open', priority: 'high', labels: ['billing'] },
    ],
    matchesText: (ticket, text) => ticket.title.toLowerCase().includes(text.toLowerCase()),
}

const TEAMS: FacetValueOption[] = [
    { value: 'team-1', label: 'Growth' },
    { value: 'team-2', label: 'Platform' },
    { value: 'team-3', label: 'Product analytics' },
]

function serverFacets(loadTeams: LoadFacetValues): ServerFacet[] {
    return [
        {
            key: 'plan',
            label: 'Plan',
            description: 'Billing plan',
            showOnFocus: true,
            order: 1,
            values: [
                { value: 'free', label: 'Free' },
                { value: 'paid', label: 'Paid', count: 1204 },
            ],
        },
        { key: 'team', label: 'Team', description: 'Owning team', showOnFocus: true, order: 2, loadValues: loadTeams },
    ]
}

const loadTeamsAfterDelay = async (search: string): Promise<FacetValueOption[]> => {
    await new Promise((resolve) => setTimeout(resolve, 300))
    return TEAMS.filter((team) => team.label?.toLowerCase().includes(search.toLowerCase()))
}

const neverLoads = (): Promise<FacetValueOption[]> => new Promise(() => {})

interface ConsumerProps {
    initial: FacetSearchValue
    narrow?: boolean
}

function Frame({ narrow, children }: { narrow?: boolean; children: React.ReactNode }): JSX.Element {
    // 520px is the scene width with the side panel open on a 1280px window.
    return <div className={clsx('flex flex-col gap-3 p-4 min-h-120', narrow && 'w-[520px]')}>{children}</div>
}

function ClientModeConsumer({ initial, narrow }: ConsumerProps): JSX.Element {
    const [value, setValue] = useState(initial)
    return (
        <Frame narrow={narrow}>
            <FacetSearchBar
                facets={TICKET_FACETS}
                data={TICKETS}
                value={value}
                onChange={setValue}
                placeholder="Search tickets, or filter with status:, priority: and more"
                dataAttr="facet-search-bar-client-story"
            />
            <LemonTable
                dataSource={filterFacetRows(TICKETS, value, TICKET_FACETS)}
                columns={[
                    { title: 'Title', dataIndex: 'title' },
                    { title: 'Status', render: (_, ticket) => capitalize(ticket.status) },
                    { title: 'Priority', render: (_, ticket) => capitalize(ticket.priority) },
                ]}
                rowKey="title"
                emptyState="No tickets match these filters"
            />
        </Frame>
    )
}

function ServerModeConsumer({
    initial,
    narrow,
    loadTeams,
}: ConsumerProps & { loadTeams: LoadFacetValues }): JSX.Element {
    const [value, setValue] = useState(initial)
    return (
        <Frame narrow={narrow}>
            <FacetSearchBar
                facets={serverFacets(loadTeams)}
                value={value}
                onChange={setValue}
                placeholder="Search accounts, or filter with plan: and team:"
                dataAttr="facet-search-bar-server-story"
            />
            <div className="text-xs text-secondary">Query sent to the API</div>
            <pre className="text-xs border rounded p-2 bg-surface-secondary">
                {JSON.stringify(toFacetQuery(value), null, 2)}
            </pre>
        </Frame>
    )
}

const meta: Meta = {
    title: 'Components/Facet search bar',
    parameters: { layout: 'fullscreen' },
}
export default meta

type ClientStory = StoryObj<typeof ClientModeConsumer>
type ServerStory = StoryObj<typeof ServerModeConsumer>

const typeInto = async (canvasElement: HTMLElement, text: string): Promise<void> => {
    const input = canvasElement.querySelector<HTMLInputElement>('input[role="combobox"]')!
    await userEvent.click(input)
    if (text) {
        await userEvent.keyboard(text)
    }
}

const NO_FILTERS: FacetSearchValue = { filters: [], text: '' }

export const ClientMode: ClientStory = {
    render: (args) => <ClientModeConsumer {...args} />,
    args: { initial: NO_FILTERS },
}

export const ClientModeFocused: ClientStory = {
    ...ClientMode,
    play: async ({ canvasElement }) => typeInto(canvasElement, ''),
}

export const ClientModeValueCounts: ClientStory = {
    render: (args) => <ClientModeConsumer {...args} />,
    args: { initial: { filters: [{ facet: 'label', value: 'bug', negated: false }], text: '' } },
    play: async ({ canvasElement }) => typeInto(canvasElement, 'status:'),
}

export const ClientModeManyPillsNarrow: ClientStory = {
    render: (args) => <ClientModeConsumer {...args} />,
    args: {
        narrow: true,
        initial: {
            filters: [
                { facet: 'status', value: 'open', negated: false },
                { facet: 'status', value: 'pending', negated: false },
                { facet: 'priority', value: 'low', negated: true },
                { facet: 'label', value: 'bug', negated: false },
            ],
            text: 'export',
        },
    },
}

export const ServerMode: ServerStory = {
    render: (args) => <ServerModeConsumer {...args} />,
    args: {
        loadTeams: loadTeamsAfterDelay,
        initial: {
            filters: [
                { facet: 'plan', value: 'paid', negated: false },
                { facet: 'team', value: 'team-2', negated: true },
            ],
            text: 'acme',
        },
    },
}

export const ServerModeSuppliedValues: ServerStory = {
    render: (args) => <ServerModeConsumer {...args} />,
    args: { loadTeams: loadTeamsAfterDelay, initial: NO_FILTERS },
    play: async ({ canvasElement }) => typeInto(canvasElement, 'plan:'),
}

export const ServerModeLoadingValues: ServerStory = {
    render: (args) => <ServerModeConsumer {...args} />,
    args: { loadTeams: neverLoads, initial: NO_FILTERS },
    play: async ({ canvasElement }) => typeInto(canvasElement, 'team:'),
}

export const ServerModeLoadedValuesNarrow: ServerStory = {
    render: (args) => <ServerModeConsumer {...args} />,
    args: { narrow: true, loadTeams: loadTeamsAfterDelay, initial: NO_FILTERS },
    play: async ({ canvasElement }) => {
        await typeInto(canvasElement, 'team:')
        await waitFor(() => {
            if (!document.querySelector('[role="option"]')) {
                throw new Error('Team values have not loaded yet')
            }
        })
    },
}
