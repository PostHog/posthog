import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_GENERATION_MESSAGES, FIXTURE_LONG_ANSWER_MESSAGE } from '../storyFixtures'
import { ThreadBubble } from './ThreadBubble'

const meta: Meta<typeof ThreadBubble> = {
    title: 'Scenes-App/AI observability/Trace view/Thread bubble',
    component: ThreadBubble,
    decorators: [
        (Story) => (
            <div className="flex flex-col">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof ThreadBubble>

export const User: Story = { args: { message: FIXTURE_GENERATION_MESSAGES[1] } }
export const AssistantSelectable: Story = { args: { message: FIXTURE_GENERATION_MESSAGES[3], onSelect: () => {} } }
export const Assistant: Story = { args: { message: FIXTURE_GENERATION_MESSAGES[3] } }
export const InternalToolCall: Story = { args: { message: FIXTURE_GENERATION_MESSAGES[2], onSelect: () => {} } }
export const LongUserMessage: Story = {
    args: {
        message: {
            ...FIXTURE_LONG_ANSWER_MESSAGE,
            role: 'user',
            parts: [FIXTURE_LONG_ANSWER_MESSAGE.parts[0], FIXTURE_LONG_ANSWER_MESSAGE.parts[0]],
        },
    },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
