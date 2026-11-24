import type { Meta, StoryObj } from '@storybook/react'

import { ListEmptyState } from './ListEmptyState'

const meta: Meta<typeof ListEmptyState> = {
    title: 'Scenes-App/AI observability/Lists/List empty state',
    component: ListEmptyState,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        title: 'No traces match these filters',
        description: 'Try a wider date range, or clear the filters to see every trace.',
        action: { label: 'Clear filters', onClick: () => {}, 'data-attr': 'traces-list-clear-filters' },
    },
}
export default meta

type Story = StoryObj<typeof ListEmptyState>

export const WithAction: Story = {}

export const WithoutAction: Story = {
    args: {
        title: 'No traces yet',
        description: 'Traces show here once your app sends its first LLM calls.',
        action: undefined,
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
