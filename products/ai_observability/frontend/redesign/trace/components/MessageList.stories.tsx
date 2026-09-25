import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_GENERATION_MESSAGES, withWidth } from '../storyFixtures'
import { MessageList } from './MessageList'

const meta: Meta<typeof MessageList> = {
    title: 'Scenes-App/AI observability/Trace view/Message list',
    component: MessageList,
}
export default meta

type Story = StoryObj<typeof MessageList>

export const Generation: Story = { args: { messages: FIXTURE_GENERATION_MESSAGES } }
export const Empty: Story = { args: { messages: [] } }
export const Narrow: Story = { args: { messages: FIXTURE_GENERATION_MESSAGES }, decorators: [withWidth(420)] }
