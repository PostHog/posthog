import type { Meta, StoryObj } from '@storybook/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { FacetDefinition, FacetSearchValue } from './facetQuery'
import { FacetSearchBar } from './FacetSearchBar'

interface Item {
    name: string
    status: string
    channel: string[]
    subjects: string[]
}

const FACETS: FacetDefinition<Item>[] = [
    {
        key: 'status',
        label: 'Status',
        description: 'Draft, active or archived',
        showOnFocus: true,
        order: 1,
        getValues: (item) => [item.status],
        formatValue: (value) => value[0].toUpperCase() + value.slice(1),
    },
    {
        key: 'channel',
        label: 'Channel',
        description: 'What it sends',
        showOnFocus: true,
        order: 2,
        getValues: (item) => item.channel,
    },
    {
        key: 'sends',
        aliases: ['subject'],
        label: 'Sends',
        description: 'Email subject',
        showOnFocus: true,
        order: 3,
        getValues: (item) => item.subjects,
    },
]

const ITEMS: Item[] = [
    { name: 'Welcome series', status: 'active', channel: ['email'], subjects: ['Welcome to Example'] },
    { name: 'Renewal reminder', status: 'draft', channel: ['email', 'sms'], subjects: ['Your plan renews soon'] },
    { name: 'Sync to CRM', status: 'draft', channel: ['webhook'], subjects: [] },
    { name: 'Spring promo', status: 'archived', channel: ['email'], subjects: ['Spring deals inside'] },
]

interface HarnessProps {
    initial: FacetSearchValue
    width?: number
}

function Harness({ initial, width }: HarnessProps): JSX.Element {
    const [value, setValue] = useState(initial)
    return (
        // A fixed width shows how the bar holds up in a narrow scene.
        <div className="p-4 min-h-120" style={width ? { width } : undefined}>
            <FacetSearchBar
                facets={FACETS}
                items={ITEMS}
                value={value}
                onChange={setValue}
                matchesText={(item, text) => item.name.toLowerCase().includes(text.toLowerCase())}
                placeholder="Search workflows, or filter with status:, channel:, from: and more"
                dataAttr="facet-search-bar-story"
            />
        </div>
    )
}

const meta: Meta<typeof Harness> = {
    title: 'Components/FacetSearchBar',
    component: Harness,
    parameters: { layout: 'fullscreen' },
    args: { initial: { filters: [], text: '' } },
}
export default meta

type Story = StoryObj<typeof Harness>

const typeInto = async (canvasElement: HTMLElement, text: string): Promise<void> => {
    const input = canvasElement.querySelector<HTMLInputElement>('input[data-attr="facet-search-bar-story"]')!
    await userEvent.click(input)
    if (text) {
        await userEvent.keyboard(text)
    }
}

export const Empty: Story = {}

export const Focused: Story = {
    play: async ({ canvasElement }) => typeInto(canvasElement, ''),
}

export const Typing: Story = {
    play: async ({ canvasElement }) => typeInto(canvasElement, 'sta'),
}

export const ValueDraftWithCounts: Story = {
    args: { initial: { filters: [{ facet: 'channel', value: 'email', negated: false }], text: '' } },
    play: async ({ canvasElement }) => typeInto(canvasElement, 'status:'),
}

export const NegatedDraft: Story = {
    play: async ({ canvasElement }) => typeInto(canvasElement, '-status:'),
}

export const ManyPillsNarrow: Story = {
    args: {
        width: 520,
        initial: {
            filters: [
                { facet: 'status', value: 'active', negated: false },
                { facet: 'status', value: 'draft', negated: false },
                { facet: 'channel', value: 'email', negated: false },
                { facet: 'channel', value: 'webhook', negated: true },
                { facet: 'sends', value: 'Your plan renews soon', negated: false },
            ],
            text: 'renewal',
        },
    },
}
