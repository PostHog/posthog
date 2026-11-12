import type { Meta, StoryObj } from '@storybook/react'
import * as React from 'react'

import { DropdownMenu, DropdownMenuContent, DropdownMenuSeparator } from '@posthog/quill-primitives'

import {
    FilterCheckboxSubMenu,
    FilterClearItem,
    FilterMenuTrigger,
    FilterRadioSubMenu,
    FilterSearchSubMenu,
} from './filter-menu'

const meta = {
    title: 'Components/FilterMenu',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

const SORTS = [
    { value: 'created', label: 'Created' },
    { value: 'viewed', label: 'Last viewed' },
]
const TYPES = [
    { value: 'dashboard', label: 'Dashboards' },
    { value: 'insight', label: 'Insights' },
    { value: 'notebook', label: 'Notebooks' },
]
const TAGS = ['finance', 'growth', 'onboarding', 'weekly'].map((tag) => ({ value: tag, label: tag }))

// The list's whole set of controls: sort first, then a row per filter, with Clear filters last. Sort never lights the dot.
export const Default: Story = {
    render: function Render() {
        const [sort, setSort] = React.useState('created')
        const [types, setTypes] = React.useState<string[]>(['insight'])
        const [tags, setTags] = React.useState<string[]>([])
        const active = types.length > 0 || tags.length > 0
        return (
            <DropdownMenu>
                <FilterMenuTrigger active={active} />
                <DropdownMenuContent align="start" className="min-w-64">
                    <FilterRadioSubMenu label="Sort by" options={SORTS} value={sort} onChange={setSort} />
                    <DropdownMenuSeparator />
                    <FilterCheckboxSubMenu
                        label="Type"
                        allLabel="All types"
                        pluralNoun="types"
                        options={TYPES}
                        selected={types}
                        onChange={setTypes}
                    />
                    <FilterSearchSubMenu
                        label="Tags"
                        allLabel="Any tag"
                        pluralNoun="tags"
                        options={TAGS}
                        selected={tags}
                        onChange={setTags}
                        searchPlaceholder="Search tags"
                        emptyText="No tag matches"
                    />
                    <FilterClearItem
                        active={active}
                        onClear={() => {
                            setTypes([])
                            setTags([])
                        }}
                    />
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
}

const MANY_TAGS = Array.from({ length: 1000 }, (_, index) => ({ value: `tag-${index}`, label: `tag-${index}` }))

export const ManySearchOptions: Story = {
    render: function Render() {
        const [tags, setTags] = React.useState<string[]>([])
        return (
            <DropdownMenu>
                <FilterMenuTrigger active={tags.length > 0} />
                <DropdownMenuContent align="start" className="min-w-64">
                    <FilterSearchSubMenu
                        label="Tags"
                        allLabel="Any tag"
                        pluralNoun="tags"
                        options={MANY_TAGS}
                        selected={tags}
                        onChange={setTags}
                        searchPlaceholder="Search tags"
                        emptyText="No tag matches"
                    />
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
}
