import { Meta, StoryObj } from '@storybook/react'

import { PhaiLegacyNudgeBanner } from './PhaiLegacyNudgeBanner'

const meta: Meta<typeof PhaiLegacyNudgeBanner> = {
    title: 'Scenes-App/PostHog AI/Legacy nudge banner',
    component: PhaiLegacyNudgeBanner,
    args: {
        mode: 'offer',
        hasQuestion: true,
        onAccept: () => {},
        onDismiss: () => {},
        onSubmitReason: () => {},
    },
    parameters: {
        layout: 'padded',
    },
}
export default meta

type Story = StoryObj<typeof PhaiLegacyNudgeBanner>

export const OfferWithQuestion: Story = {}

export const OfferWithoutQuestion: Story = {
    args: { hasQuestion: false },
}

export const ReasonPrompt: Story = {
    args: { mode: 'reason' },
}

// The side panel is the tightest host the banner has to survive, and it is where wrapping shows up first.
export const InNarrowPanel: Story = {
    decorators: [
        (Story) => (
            <div className="w-[400px] border border-primary rounded">
                <Story />
            </div>
        ),
    ],
}

export const ReasonPromptInNarrowPanel: Story = {
    args: { mode: 'reason' },
    decorators: [
        (Story) => (
            <div className="w-[400px] border border-primary rounded">
                <Story />
            </div>
        ),
    ],
}
