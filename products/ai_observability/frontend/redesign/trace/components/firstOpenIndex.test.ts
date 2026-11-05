import { MessageRole, MessagesOpening, ThreadMessage } from '../types'
import { firstOpenIndex } from './firstOpenIndex'

function conversation(roles: MessageRole[]): ThreadMessage[] {
    return roles.map((role, index) => ({
        id: `m-${index}`,
        role,
        parts: [{ kind: 'text', text: role }],
        isInternal: false,
        sourceNodeId: 'gen-1',
    }))
}

describe('firstOpenIndex', () => {
    test.each<[string, MessageRole[], MessagesOpening, number]>([
        [
            'opens the last user message and the tool loop after it',
            ['system', 'user', 'assistant', 'tool', 'user', 'assistant', 'tool'],
            'lastTurn',
            4,
        ],
        ['opens a plain chat from its last user message', ['system', 'user', 'assistant', 'user'], 'lastTurn', 3],
        ['opens everything when no user message exists', ['system', 'assistant', 'tool'], 'lastTurn', 0],
        ['opens everything when asked to', ['system', 'user', 'assistant', 'user'], 'everything', 0],
    ])('%s', (_, roles, opening, expected) => {
        expect(firstOpenIndex(conversation(roles), opening)).toBe(expected)
    })
})
