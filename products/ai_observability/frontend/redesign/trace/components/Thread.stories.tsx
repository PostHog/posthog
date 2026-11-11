import type { Meta, StoryObj } from '@storybook/react'

import { anthropicMessagesThinkingToolUse } from '../sampleFixtures/anthropicMessagesThinkingToolUse'
import { langchainCerebrasImageError } from '../sampleFixtures/langchainCerebrasImageError'
import { messagesSides } from '../sampleFixtures/sampleContent'
import { FIXTURE_GENERATION_INPUT, FIXTURE_TURN, withWidth } from '../storyFixtures'
import { ConversationTurn } from '../types'
import { Thread } from './Thread'

const meta: Meta<typeof Thread> = {
    title: 'Scenes-App/AI observability/Trace view/Thread',
    component: Thread,
    args: { onSelectMessage: () => {} },
}
export default meta

type Story = StoryObj<typeof Thread>

function ready(turns: ConversationTurn[]): Story['args'] {
    return { conversation: { status: 'ready', turns, activeTurnId: 'trace-1' } }
}

export const SingleTurn: Story = { args: ready([FIXTURE_TURN]) }
export const WithSearchHighlight: Story = { args: { ...ready([FIXTURE_TURN]), highlightQuery: 'seats' } }
export const Loading: Story = {
    args: { conversation: { status: 'loading' } },
    decorators: [withWidth(720)],
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const LoadError: Story = {
    args: {
        conversation: {
            status: 'error',
            message: 'The conversation could not be loaded. Reload the page to try again.',
        },
    },
    decorators: [withWidth(720)],
}
export const Empty: Story = { args: ready([{ ...FIXTURE_TURN, ...messagesSides([], []) }]) }
export const SystemOnly: Story = {
    args: ready([{ ...FIXTURE_TURN, ...messagesSides([FIXTURE_GENERATION_INPUT[0]], []) }]),
}
export const ErrorWithoutMessages: Story = {
    args: ready([{ ...FIXTURE_TURN, ...messagesSides([], []), error: 'APIConnectionError: Connection reset by peer' }]),
}
export const JsonOutput: Story = {
    args: ready([
        {
            ...FIXTURE_TURN,
            output: { kind: 'json', value: { plan: 'Teams', seatsAdded: 2, invoiceChangeUsd: 40 } },
        },
    ]),
}
export const AnthropicThinkingAndTools: Story = { args: { conversation: anthropicMessagesThinkingToolUse.thread } }
export const ImageInputWithError: Story = { args: { conversation: langchainCerebrasImageError.thread } }
export const Narrow: Story = { args: ready([FIXTURE_TURN]), decorators: [withWidth(420)] }
