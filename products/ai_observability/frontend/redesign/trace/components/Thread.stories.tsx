import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_GENERATION_MESSAGES, FIXTURE_TURN, withWidth } from '../storyFixtures'
import { Thread } from './Thread'

const meta: Meta<typeof Thread> = {
    title: 'Scenes-App/AI observability/Trace view/Thread',
    component: Thread,
    args: { activeTurnId: 'trace-1', onSelectMessage: () => {} },
}
export default meta

type Story = StoryObj<typeof Thread>

export const SingleTurn: Story = { args: { turns: [FIXTURE_TURN] } }
export const Empty: Story = { args: { turns: [{ ...FIXTURE_TURN, messages: [] }] } }
export const SystemOnly: Story = { args: { turns: [{ ...FIXTURE_TURN, messages: [FIXTURE_GENERATION_MESSAGES[0]] }] } }
export const Narrow: Story = { args: { turns: [FIXTURE_TURN] }, decorators: [withWidth(420)] }
