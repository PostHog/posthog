import { ConversationTurn, NodeSideContent } from '../types'
import { turnHasContent } from './conversationalMessages'

const NO_MESSAGES: NodeSideContent = { kind: 'messages', messages: [] }
const SYSTEM_ONLY: NodeSideContent = {
    kind: 'messages',
    messages: [
        {
            id: 's',
            role: 'system',
            parts: [{ kind: 'text', text: 'Be brief.' }],
            isInternal: false,
            sourceNodeId: null,
        },
    ],
}

const INTERNAL_ONLY: NodeSideContent = {
    kind: 'messages',
    messages: [
        {
            id: 'i',
            role: 'assistant',
            parts: [{ kind: 'text', text: 'Checking the seat history.' }],
            isInternal: true,
            sourceNodeId: null,
        },
    ],
}

function turn(input: NodeSideContent, output: NodeSideContent): ConversationTurn {
    return { id: 'trace-1', timestamp: '2026-09-01T10:15:00Z', waitMs: null, input, output, error: null }
}

describe('turnHasContent', () => {
    test.each<[string, ConversationTurn, boolean, boolean]>([
        ['no messages on either side', turn(NO_MESSAGES, NO_MESSAGES), false, false],
        ['only a system prompt', turn(SYSTEM_ONLY, NO_MESSAGES), false, false],
        ['an empty json side', turn(NO_MESSAGES, { kind: 'json', value: null }), false, false],
        ['a json side with a value', turn(NO_MESSAGES, { kind: 'json', value: { seatsAdded: 2 } }), false, true],
        ['only internal messages, which a toggle shows', turn(INTERNAL_ONLY, NO_MESSAGES), false, true],
        ['only internal messages, with only the conversation shown', turn(INTERNAL_ONLY, NO_MESSAGES), true, false],
    ])('%s', (_name, value, conversationOnly, expected) => {
        expect(turnHasContent(value, conversationOnly)).toBe(expected)
    })
})
