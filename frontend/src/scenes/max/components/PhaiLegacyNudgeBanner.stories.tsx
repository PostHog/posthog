import { Meta, StoryObj } from '@storybook/react'

import { PhaiLegacyNudgeBanner } from './PhaiLegacyNudgeBanner'

const meta: Meta<typeof PhaiLegacyNudgeBanner> = {
    title: 'Scenes-App/PostHog AI/Legacy nudge banner',
    component: PhaiLegacyNudgeBanner,
    args: {
        mode: 'offer',
        hasQuestion: true,
        otherReasonSelected: false,
        otherReasonText: '',
        onAccept: () => {},
        onDismiss: () => {},
        onSubmitReason: () => {},
        onSelectOtherReason: () => {},
        onChangeOtherReasonText: () => {},
        onSubmitOtherReason: () => {},
    },
    parameters: {
        // Fullscreen so the centered chat column reads at its real width instead of inside Storybook's inset.
        layout: 'fullscreen',
    },
}
export default meta

type Story = StoryObj<typeof PhaiLegacyNudgeBanner>

// The side panel is the tightest host the banner has to survive, and it is where wrapping shows up first.
const narrowPanel = [
    (Story: () => JSX.Element) => (
        <div className="w-[400px] border border-primary rounded">
            <Story />
        </div>
    ),
]

export const OfferWithQuestion: Story = {}

export const OfferWithoutQuestion: Story = {
    args: { hasQuestion: false },
}

export const ReasonPrompt: Story = {
    args: { mode: 'reason' },
}

export const OtherReasonPrompt: Story = {
    args: { mode: 'reason', otherReasonSelected: true, otherReasonText: 'It forgets what I asked it' },
}

export const InNarrowPanel: Story = {
    decorators: narrowPanel,
}

export const ReasonPromptInNarrowPanel: Story = {
    args: { mode: 'reason' },
    decorators: narrowPanel,
}

export const OtherReasonPromptInNarrowPanel: Story = {
    args: { mode: 'reason', otherReasonSelected: true, otherReasonText: 'It forgets what I asked it' },
    decorators: narrowPanel,
}
