import type { Meta, StoryObj } from '@storybook/react'

import { IconCalendar, IconFilter } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { ListToolbar } from './ListToolbar'

const meta: Meta<typeof ListToolbar> = {
    title: 'Scenes-App/AI observability/Lists/List toolbar',
    component: ListToolbar,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        search: '',
        onSearchChange: () => {},
        searchPlaceholder: 'Search names, inputs and outputs',
        filters: (
            <LemonButton type="secondary" size="small" icon={<IconFilter />}>
                Filter
            </LemonButton>
        ),
        testAccounts: (
            <LemonSwitch bordered size="small" checked label="Filter out internal and test users" onChange={() => {}} />
        ),
        dateRange: (
            <LemonButton type="secondary" size="small" icon={<IconCalendar />}>
                Last 7 days
            </LemonButton>
        ),
        onReload: () => {},
        reloading: false,
        'data-attr': 'traces-list',
    },
}
export default meta

type Story = StoryObj<typeof ListToolbar>

export const Wide: Story = {}

export const Reloading: Story = { args: { search: 'refund policy', reloading: true } }

export const WithoutSearch: Story = { args: { onSearchChange: undefined } }

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-96">
                <StoryComponent />
            </div>
        ),
    ],
}
