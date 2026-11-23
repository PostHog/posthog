import type { Meta, StoryObj } from '@storybook/react'

import { ListErrorState } from './ListErrorState'

const meta: Meta<typeof ListErrorState> = {
    title: 'Scenes-App/AI observability/Lists/List error state',
    component: ListErrorState,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        title: "We couldn't load traces",
        description: 'Something went wrong while loading them. Try again in a moment.',
        retry: { onClick: () => {}, 'data-attr': 'traces-list-retry' },
    },
}
export default meta

type Story = StoryObj<typeof ListErrorState>

export const WithRetry: Story = {}

export const WithoutRetry: Story = { args: { retry: undefined } }

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-60">
                <StoryComponent />
            </div>
        ),
    ],
}
