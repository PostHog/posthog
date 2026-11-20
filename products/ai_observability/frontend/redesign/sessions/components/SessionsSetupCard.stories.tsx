import type { Meta, StoryObj } from '@storybook/react'

import { SessionsSetupCard } from './SessionsSetupCard'

const meta: Meta<typeof SessionsSetupCard> = {
    title: 'Scenes-App/AI observability/Sessions/Sessions setup card',
    component: SessionsSetupCard,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { tracesHref: '/ai-observability/traces?date_from=-7d' },
}
export default meta

type Story = StoryObj<typeof SessionsSetupCard>

export const Wide: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="@container/main-content w-240">
                <StoryComponent />
            </div>
        ),
    ],
}

export const Narrow: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="@container/main-content w-100">
                <StoryComponent />
            </div>
        ),
    ],
}
