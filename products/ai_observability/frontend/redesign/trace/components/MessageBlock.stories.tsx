import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_GENERATION_MESSAGES } from '../storyFixtures'
import { MessageBlock } from './MessageBlock'

const meta: Meta<typeof MessageBlock> = {
    title: 'Scenes-App/AI observability/Trace view/Message block',
    component: MessageBlock,
}
export default meta

export const System: StoryObj<typeof MessageBlock> = { args: { message: FIXTURE_GENERATION_MESSAGES[0] } }
export const ToolCall: StoryObj<typeof MessageBlock> = { args: { message: FIXTURE_GENERATION_MESSAGES[2] } }
