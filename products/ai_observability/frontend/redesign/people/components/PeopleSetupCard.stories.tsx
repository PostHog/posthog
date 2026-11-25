import type { Meta, StoryObj } from '@storybook/react'

import { PeopleSetupCard } from './PeopleSetupCard'

const meta: Meta<typeof PeopleSetupCard> = {
    title: 'Scenes-App/AI observability/People/People setup card',
    component: PeopleSetupCard,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        docsUrl: 'https://posthog.com/docs/ai-observability/installation',
        tracesHref: '/ai-observability/traces',
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-80">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof PeopleSetupCard>

export const NarrowContainer: Story = {}
