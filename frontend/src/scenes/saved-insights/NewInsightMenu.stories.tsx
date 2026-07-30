import { Meta, StoryObj } from '@storybook/react'

import { NewInsightMenuChipsOverlay, NewInsightMenuGroupedOverlay } from './NewInsightMenu'

const meta: Meta = {
    title: 'Scenes-App/Saved Insights/New Insight Menu',
}
export default meta

type Story = StoryObj

export const ChipsOverlay: Story = {
    render: () => (
        <div className="border border-primary rounded bg-surface-primary w-fit p-1">
            <NewInsightMenuChipsOverlay />
        </div>
    ),
}

export const GroupedOverlay: Story = {
    render: () => (
        <div className="border border-primary rounded bg-surface-primary w-fit p-1">
            <NewInsightMenuGroupedOverlay />
        </div>
    ),
}
