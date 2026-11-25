import type { Meta, StoryObj } from '@storybook/react'

import { messagesSides } from '../sampleFixtures/sampleContent'
import { FIXTURE_ATTACHMENT_PARTS, FIXTURE_TURN, withWidth } from '../storyFixtures'
import { ThreadTurn } from './ThreadTurn'

const meta: Meta<typeof ThreadTurn> = {
    title: 'Scenes-App/AI observability/Trace view/Thread turn',
    component: ThreadTurn,
    args: { turn: FIXTURE_TURN, onSelectMessage: () => {} },
}
export default meta

export const Default: StoryObj<typeof ThreadTurn> = { args: { isActive: false } }
export const Active: StoryObj<typeof ThreadTurn> = { args: { isActive: true } }
export const WithError: StoryObj<typeof ThreadTurn> = {
    args: {
        isActive: false,
        turn: {
            ...FIXTURE_TURN,
            ...messagesSides(
                [
                    {
                        id: 'm-user-image',
                        role: 'user',
                        parts: [{ kind: 'text', text: 'What does this chart show?' }, FIXTURE_ATTACHMENT_PARTS[0]],
                        isInternal: false,
                        sourceNodeId: 'gen-answer',
                    },
                ],
                []
            ),
            error: 'BadRequestError: 400 This model does not accept image input',
        },
    },
}

const sessionTurn = {
    ...FIXTURE_TURN,
    trace: {
        name: 'answer-billing-question',
        totals: {
            costUsd: 0.0021,
            inputTokens: 2_100,
            outputTokens: 474,
            cacheReadTokens: null,
            cacheWriteTokens: null,
            latencyMs: 1_840,
        },
    },
}

export const InSession: StoryObj<typeof ThreadTurn> = {
    args: { isActive: false, turn: sessionTurn, showTiming: true },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export const InSessionNarrow: StoryObj<typeof ThreadTurn> = {
    ...InSession,
    decorators: [withWidth(320)],
}
export const InSessionLongTraceName: StoryObj<typeof ThreadTurn> = {
    ...InSessionNarrow,
    args: {
        ...InSession.args,
        turn: {
            ...sessionTurn,
            trace: {
                ...sessionTurn.trace,
                name: 'support-agent/answer-billing-question-with-invoice-history-and-seat-changes',
            },
        },
    },
}
