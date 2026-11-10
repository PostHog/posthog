import { cleanup, render } from '@testing-library/react'

import { ConversationTurn } from '../types'
import { ThreadTurn } from './ThreadTurn'

const turn: ConversationTurn = {
    id: 'trace-1',
    timestamp: '2026-09-01T10:15:00Z',
    error: null,
    input: { kind: 'messages', messages: [] },
    output: {
        kind: 'messages',
        messages: [
            {
                id: 'gen-1-out-0',
                role: 'assistant',
                parts: [{ kind: 'text', text: 'Two seats were added.' }],
                isInternal: false,
                sourceNodeId: 'gen-1',
            },
        ],
    },
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

    test('shows a side the server returned as json in its place', () => {
        const { getByText } = render(
            <ThreadTurn
                turn={{ ...turn, input: { kind: 'json', value: 'Why did my invoice go up?' } }}
                isActive={false}
                onSelectMessage={() => {}}
            />
        )

        expect(getByText('Input')).toBeTruthy()
        expect(getByText('Why did my invoice go up?')).toBeTruthy()
        expect(getByText('Two seats were added.')).toBeTruthy()
    })

    test.each([
        ['cuts a bubble taller than the window', null, 1],
        ['shows a bubble that holds the search query in full', 'seats', 0],
    ])('%s', (_name, highlightQuery, readMoreCount) => {
        const height = jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(window.innerHeight + 1)
        try {
            const { queryAllByText } = render(
                <ThreadTurn turn={turn} isActive={false} onSelectMessage={() => {}} highlightQuery={highlightQuery} />
            )

            expect(queryAllByText('Show more')).toHaveLength(readMoreCount)
        } finally {
            height.mockRestore()
        }
    })
})
