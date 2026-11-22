import type { Meta, StoryObj } from '@storybook/react'

import { QuickFilterChips } from './QuickFilterChips'

const meta: Meta<typeof QuickFilterChips> = {
    title: 'Scenes-App/AI observability/Lists/Quick filter chips',
    component: QuickFilterChips,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        chips: [
            { id: 'errors', label: 'Errors', count: 12, tone: 'danger' },
            { id: 'feedback', label: 'User feedback', count: 9 },
            { id: 'reviewed', label: 'Reviewed', count: 1480 },
        ],
        active: 'errors',
        onToggle: () => {},
        'data-attr': 'traces-list',
    },
}
export default meta

type Story = StoryObj<typeof QuickFilterChips>

export const WithCounts: Story = {}

export const CountsLoading: Story = {
    args: {
        chips: [
            { id: 'errors', label: 'Errors', count: null, tone: 'danger' },
            { id: 'feedback', label: 'User feedback', count: null },
        ],
        active: null,
    },
}

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-60">
                <StoryComponent />
            </div>
        ),
    ],
}
