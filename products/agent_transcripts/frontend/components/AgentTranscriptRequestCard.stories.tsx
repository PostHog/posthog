import { Meta, StoryObj } from '@storybook/react'

import { AgentTranscriptRequestCard } from './AgentTranscriptRequestCard'

const meta: Meta<typeof AgentTranscriptRequestCard> = {
    title: 'Scenes-App/Agent transcripts/Request card',
    component: AgentTranscriptRequestCard,
    args: {
        variant: 'control',
        stage: 'request',
        onOpen: () => {},
        onDismiss: () => {},
    },
    decorators: [
        (Story) => (
            // The card floats at this width over the bottom left corner of the scene.
            <div className="w-80 p-4">
                <Story />
            </div>
        ),
    ],
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof AgentTranscriptRequestCard>

export const Control: Story = {}

export const MerchCode: Story = {
    args: { variant: 'test' },
}

export const ChangesRequested: Story = {
    args: { stage: 'changes_requested' },
}
