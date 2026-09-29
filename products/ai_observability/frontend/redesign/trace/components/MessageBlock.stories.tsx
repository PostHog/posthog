import type { Meta, StoryObj } from '@storybook/react'

import { anthropicThinkingMessages } from '../sampleFixtures/anthropicMessagesThinkingToolUse'
import { FIXTURE_GENERATION_MESSAGES } from '../storyFixtures'
import { MessageBlock } from './MessageBlock'

const meta: Meta<typeof MessageBlock> = {
    title: 'Scenes-App/AI observability/Trace view/Message block',
    component: MessageBlock,
}
export default meta

export const System: StoryObj<typeof MessageBlock> = { args: { message: FIXTURE_GENERATION_MESSAGES[0] } }
export const ToolCall: StoryObj<typeof MessageBlock> = { args: { message: FIXTURE_GENERATION_MESSAGES[2] } }
export const User: StoryObj<typeof MessageBlock> = { args: { message: FIXTURE_GENERATION_MESSAGES[1] } }
export const Assistant: StoryObj<typeof MessageBlock> = { args: { message: FIXTURE_GENERATION_MESSAGES[3] } }
export const ThinkingAndToolCall: StoryObj<typeof MessageBlock> = { args: { message: anthropicThinkingMessages[1] } }
