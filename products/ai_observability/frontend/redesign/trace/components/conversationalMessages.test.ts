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

function turn(input: NodeSideContent, output: NodeSideContent): ConversationTurn {
    return { id: 'trace-1', timestamp: '2026-09-01T10:15:00Z', input, output, error: null }
}

describe('turnHasContent', () => {
    test.each<[string, ConversationTurn, boolean]>([
        ['no messages on either side', turn(NO_MESSAGES, NO_MESSAGES), false],
        ['only a system prompt', turn(SYSTEM_ONLY, NO_MESSAGES), false],
        ['an empty json side', turn(NO_MESSAGES, { kind: 'json', value: null }), false],
        ['a json side with a value', turn(NO_MESSAGES, { kind: 'json', value: { seatsAdded: 2 } }), true],
    ])('%s', (_name, value, expected) => {
        expect(turnHasContent(value)).toBe(expected)
    })
})
