import { Meta, StoryObj } from '@storybook/react'

import { NewInsightMenuOverlay } from './NewInsightMenu'

const meta: Meta<typeof NewInsightMenuOverlay> = {
    title: 'Scenes-App/Saved Insights/New Insight Menu',
    component: NewInsightMenuOverlay,
}
export default meta

type Story = StoryObj<typeof NewInsightMenuOverlay>

export const Overlay: Story = {
    render: () => (
        <div className="border border-primary rounded bg-surface-primary w-fit p-1">
            <NewInsightMenuOverlay />
        </div>
    ),
}
