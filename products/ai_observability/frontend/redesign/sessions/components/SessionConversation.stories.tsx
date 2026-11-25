import type { Meta, StoryObj } from '@storybook/react'

import { messagesSides } from '../../trace/sampleFixtures/sampleContent'
import { makeMessage } from '../../trace/testFixtures'
import type { ConversationTurn, ThreadMessage } from '../../trace/types'
import { SessionConversation } from './SessionConversation'

const START_MS = Date.parse('2026-09-01T10:03:00Z')

const QUESTIONS = [
    ['Why did my invoice go up this month?', 'Two seats were added on 12 August, which adds 40 USD a month.'],
    ['Who added them?', 'Both were added by an admin on your team from Billing settings.'],
    ['Can I remove one seat?', 'Yes. Open Billing settings and lower the seat count to 4.'],
    ['Will I get a refund for this month?', 'The current month stays as billed. The next invoice drops by 20 USD.'],
    ['And if I remove both?', 'The next invoice drops by 40 USD.'],
    ['Thanks, that is all.', 'Glad to help.'],
    ['One more thing: where is the invoice PDF?', 'Each invoice has a download link in Billing history.'],
    ['Found it, thanks.', 'You are welcome.'],
]

function turn(index: number, overrides: Partial<ConversationTurn> = {}): ConversationTurn {
    const [question, answer] = QUESTIONS[index % QUESTIONS.length]
    const traceId = `trace-${index}`
    const message = (role: 'user' | 'assistant', text: string): ThreadMessage =>
        makeMessage({ id: `${traceId}-${role}`, role, parts: [{ kind: 'text', text }], sourceNodeId: `${traceId}-gen` })
    // A silence of over an hour after the fourth turn shows the divider.
    const minutes = index < 4 ? index : index + 70
    return {
        id: traceId,
        timestamp: new Date(START_MS + minutes * 60_000).toISOString(),
        waitMs: index === 1 ? 18_000 : 2_400,
        waitSlow: index === 1,
        silenceBeforeMs: index === 4 ? 71 * 60_000 : null,
        error: null,
        ...messagesSides([message('user', question)], [message('assistant', answer)]),
        ...overrides,
    }
}

const meta: Meta<typeof SessionConversation> = {
    title: 'Scenes-App/AI observability/Sessions/Session conversation',
    component: SessionConversation,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        olderEdge: 'end',
        newerEdge: 'end',
        conversationOnly: false,
        onSelectMessage: () => {},
        onLoadOlder: () => {},
        onLoadNewer: () => {},
        onReload: () => {},
        onRetrySides: () => {},
        className: 'h-120 w-170',
        status: 'ready',
        turns: [0, 1, 2, 3, 4].map((index) => turn(index)),
        activeTurnId: null,
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-fit rounded border">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof SessionConversation>

export const Loading: Story = {
    args: { status: 'loading', turns: [] },
    parameters: { testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: false } },
}

export const Ready: Story = {}

export const Narrow: Story = { args: { className: 'h-120 w-50' } }

export const LongWithPaging: Story = {
    args: {
        turns: [2, 3, 4, 5, 6, 7].map((index) => turn(index)),
        activeTurnId: 'trace-3',
        olderEdge: 'more',
        newerEdge: 'loading',
    },
    parameters: { testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: false } },
}

export const MessagesLoading: Story = {
    args: {
        turns: [
            turn(0, { sidesStatus: 'ready' }),
            ...[1, 2].map((index) => turn(index, { ...messagesSides([], []), sidesStatus: 'loading' })),
        ],
    },
    parameters: { testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: false } },
}

export const MessagesFailedOrEmpty: Story = {
    args: {
        turns: [
            turn(0, { sidesStatus: 'ready' }),
            turn(1, { ...messagesSides([], []), sidesStatus: 'error' }),
            turn(2, { ...messagesSides([], []), sidesStatus: 'ready' }),
        ],
    },
}

export const ErroredTurns: Story = {
    args: {
        turns: [
            turn(0),
            turn(1, {
                output: { kind: 'messages', messages: [] },
                error: 'RateLimitError: Rate limit reached for requests',
            }),
            turn(2, {
                input: { kind: 'messages', messages: [] },
                missingReasons: { input: 'too_large', output: null },
            }),
        ],
        newerEdge: 'failed',
    },
}

export const FailedToLoad: Story = {
    args: { status: 'failed', turns: [] },
}

export const Empty: Story = { args: { turns: [] } }

export const NotFound: Story = { args: { status: 'not_found', turns: [] } }
