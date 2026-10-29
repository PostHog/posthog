import { MessagePart, ThreadMessage } from '../types'
import { messageContainsText } from './messageContainsText'

function message(part: MessagePart): ThreadMessage {
    return { id: 'm1', role: 'assistant', parts: [part], isInternal: false, sourceNodeId: 'gen-1' }
}

const CASES: [string, MessagePart, boolean][] = [
    ['a text part, ignoring case', { kind: 'text', text: 'Your Invoice went up.' }, true],
    ['a tool call argument', { kind: 'toolCall', name: 'lookup', args: { id: 'invoice-42' } }, true],
    ['a thinking part', { kind: 'thinking', text: 'The invoice changed in August.' }, true],
    ['a message without the text', { kind: 'text', text: 'Two seats were added.' }, false],
]

describe('messageContainsText', () => {
    test.each(CASES)('finds the query in %s', (_name, part, expected) => {
        expect(messageContainsText(message(part), 'invoice')).toBe(expected)
    })
})
