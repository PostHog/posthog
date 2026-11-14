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

    test.each([
        ['as plain text', 'Why did my invoice go up?', 'Why did my invoice go up?'],
        ['as the fields of a JSON string', '{"question": "Why did my invoice go up?"}', 'question'],
    ])('shows a side the server returned as json in its place, %s', (_name, value, shownText) => {
        const { getByText } = render(
            <ThreadTurn
                turn={{ ...turn, input: { kind: 'json', value } }}
                isActive={false}
                onSelectMessage={() => {}}
            />
        )

        expect(getByText('Input')).toBeTruthy()
        expect(getByText(shownText)).toBeTruthy()
        expect(getByText('Two seats were added.')).toBeTruthy()
    })

    const jsonTurn: ConversationTurn = {
        ...turn,
        input: { kind: 'json', value: '{"filters": {"types": ["invoice"]}}' },
    }

    test.each([
        ['cuts a bubble taller than the window', turn, window.innerHeight + 1, null, 1],
        ['shows a bubble that holds the search query in full', turn, window.innerHeight + 1, 'seats', 0],
        ['cuts a JSON field taller than half the window', jsonTurn, window.innerHeight / 2 + 1, null, 1],
    ])('%s', (_name, shownTurn, contentHeight, highlightQuery, readMoreCount) => {
        const height = jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(contentHeight)
        try {
            const { queryAllByText } = render(
                <ThreadTurn
                    turn={shownTurn}
                    isActive={false}
                    onSelectMessage={() => {}}
                    highlightQuery={highlightQuery}
                />
            )

            expect(queryAllByText('Show more')).toHaveLength(readMoreCount)
        } finally {
            height.mockRestore()
        }
    })
})
