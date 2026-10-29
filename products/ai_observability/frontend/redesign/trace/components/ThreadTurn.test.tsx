import { cleanup, render } from '@testing-library/react'

import { ConversationTurn } from '../types'
import { ThreadTurn } from './ThreadTurn'

const turn: ConversationTurn = {
    id: 'trace-1',
    timestamp: '2026-09-01T10:15:00Z',
    error: null,
    messages: [
        {
            id: 'gen-1-out-0',
            role: 'assistant',
            parts: [{ kind: 'text', text: 'Two seats were added.' }],
            isInternal: false,
            sourceNodeId: 'gen-1',
        },
    ],
}

describe('ThreadTurn', () => {
    afterEach(cleanup)

    test.each([
        ['matches, even where the text does not show the query', new Set(['gen-1']), false],
        ['does not match', new Set(['gen-2']), true],
    ])('fades a message by whether its step %s', (_name, matchingNodeIds, faded) => {
        const { getByText } = render(
            <ThreadTurn turn={turn} isActive={false} onSelectMessage={() => {}} matchingNodeIds={matchingNodeIds} />
        )

        expect(getByText('Two seats were added.').closest('.opacity-50') !== null).toBe(faded)
    })
})
