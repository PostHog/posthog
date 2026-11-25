import type { Meta, StoryObj } from '@storybook/react'

import { anthropicMessagesThinkingToolUse } from '../sampleFixtures/anthropicMessagesThinkingToolUse'
import { langchainCerebrasImageError } from '../sampleFixtures/langchainCerebrasImageError'
import { messagesSides } from '../sampleFixtures/sampleContent'
import { FIXTURE_GENERATION_INPUT, FIXTURE_TURN, withWidth } from '../storyFixtures'
import { ConversationTurn, ThreadMessage } from '../types'
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

function sessionTurn(
    index: number,
    timestamp: string,
    waitMs: number,
    question: string,
    answer: string,
    internal: ThreadMessage[] = [],
    timing: Pick<ConversationTurn, 'waitSlow' | 'silenceBeforeMs'> = {}
): ConversationTurn {
    const message = (id: string, role: 'user' | 'assistant', text: string, isInternal = false): ThreadMessage => ({
        id,
        role,
        parts: [{ kind: 'text', text }],
        isInternal,
        sourceNodeId: `gen-${index}`,
    })
    return {
        id: `trace-${index}`,
        timestamp,
        waitMs,
        error: null,
        ...messagesSides(
            [message(`q-${index}`, 'user', question), ...internal],
            [message(`a-${index}`, 'assistant', answer)]
        ),
        ...timing,
    }
}

const SESSION_TURNS: ConversationTurn[] = [
    sessionTurn(1, '2026-09-01T10:03:00Z', 2_100, 'Why did my invoice go up?', 'Two seats were added on 12 August.'),
    sessionTurn(
        2,
        '2026-09-01T10:04:00Z',
        18_000,
        'Can you list every seat change?',
        'Here are the last six seat changes.',
        [
            {
                id: 'internal-2',
                role: 'assistant',
                parts: [{ kind: 'text', text: 'Looking up the seat history.' }],
                isInternal: true,
                sourceNodeId: 'gen-2',
            },
        ],
        { waitSlow: true }
    ),
    sessionTurn(3, '2026-09-01T10:05:00Z', 1_400, 'Thanks. Can I remove one seat?', 'Yes, from Billing settings.'),
    sessionTurn(
        4,
        '2026-09-01T11:20:00Z',
        3_200,
        'I removed the seat. What changes?',
        'The next invoice drops by 20 USD.',
        [],
        { silenceBeforeMs: 4_498_600 }
    ),
    sessionTurn(5, '2026-09-01T11:21:00Z', 2_800, 'And the current month?', 'The current month stays as billed.'),
    sessionTurn(6, '2026-09-01T11:22:00Z', 900, 'Great, that is all.', 'Glad to help.'),
]

function sessionArgs(): Story['args'] {
    return {
        conversation: { status: 'ready', turns: SESSION_TURNS, activeTurnId: null },
        showTiming: true,
    }
}

export const SessionTurnsWithTiming: Story = { args: sessionArgs(), decorators: [withWidth(470)] }
export const ConversationOnly: Story = {
    args: { ...sessionArgs(), conversationOnly: true },
    decorators: [withWidth(470)],
}
