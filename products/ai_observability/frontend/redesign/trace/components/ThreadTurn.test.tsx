import { cleanup, fireEvent, render } from '@testing-library/react'

import { ConversationTurn } from '../types'
import { ThreadTurn } from './ThreadTurn'

const turn: ConversationTurn = {
    id: 'trace-1',
    timestamp: '2026-09-01T10:15:00Z',
    waitMs: null,
    error: null,
    input: {
        kind: 'messages',
        messages: [
            {
                id: 'gen-1-in-0',
                role: 'user',
                parts: [{ kind: 'text', text: 'Add two seats.' }],
                isInternal: false,
                sourceNodeId: 'gen-1',
            },
            {
                id: 'gen-1-in-1',
                role: 'assistant',
                parts: [{ kind: 'text', text: 'Checking the seat history.' }],
                isInternal: true,
                sourceNodeId: 'gen-1',
            },
        ],
    },
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
        ['cuts a bubble taller than the window', null, 2],
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

    describe('timing', () => {
        const timed = (waitMs: number | null): JSX.Element => (
            <ThreadTurn turn={{ ...turn, waitMs }} isActive={false} onSelectMessage={() => {}} showTiming />
        )

        test('shows timing beside the user message', () => {
            const { getByText } = render(timed(2_100))

            expect(getByText(/10:15/)).toBeTruthy()
            expect(getByText(/2\.1s/)).toBeTruthy()
        })

        test.each([
            [18_000, true],
            [2_100, false],
        ])('marks a %sms wait as slow: %s', (waitMs, slow) => {
            const { getByText } = render(timed(waitMs))

            expect(getByText(/\ds$/).className.includes('text-warning')).toBe(slow)
        })

        test('shows no wait when latency is null', () => {
            const { getByText, queryByText } = render(timed(null))

            expect(getByText(/10:15/)).toBeTruthy()
            expect(queryByText(/\ds$/)).toBeNull()
        })

        test('shows no timing unless asked', () => {
            const { queryByText } = render(
                <ThreadTurn turn={{ ...turn, waitMs: 2_100 }} isActive={false} onSelectMessage={() => {}} />
            )

            expect(queryByText(/10:15/)).toBeNull()
        })
    })

    describe('read apart from the turn', () => {
        test.each([
            [
                'a missing user message',
                {
                    ...turn,
                    input: { kind: 'messages', messages: [] },
                    missingReasons: { input: 'too_large', output: null },
                },
                "The user's message is too large to show here.",
            ],
            [
                'a cut answer',
                { ...turn, missingReasons: { input: null, output: 'timed_out' } },
                'Part of the answer took too long to load.',
            ],
        ] satisfies [string, ConversationTurn, string][])(
            'says why for %s and opens the trace on request',
            (_name, missingTurn, notice) => {
                const onSelectMessage = jest.fn()
                const { getByText } = render(
                    <ThreadTurn turn={missingTurn} isActive={false} onSelectMessage={onSelectMessage} />
                )

                expect(getByText(notice)).toBeTruthy()
                fireEvent.click(getByText('Open trace'))
                expect(onSelectMessage).toHaveBeenCalledWith('trace-1', 'trace-1')
            }
        )

        test('a failed read offers a retry instead of an empty turn', () => {
            const onRetry = jest.fn()
            const { getAllByText, queryByText } = render(
                <ThreadTurn
                    turn={{ ...turn, pending: 'error' }}
                    isActive={false}
                    onSelectMessage={() => {}}
                    onRetry={onRetry}
                />
            )

            expect(queryByText('Add two seats.')).toBeNull()
            // The banner renders its action twice, one for each container width.
            fireEvent.click(getAllByText('Try again')[0])
            expect(onRetry).toHaveBeenCalled()
        })
    })

    test('conversation only hides internal messages and the toggle', () => {
        const props = { turn, isActive: false, onSelectMessage: () => {} }
        const { getByText, queryByText, rerender } = render(<ThreadTurn {...props} />)
        expect(getByText('Show 1 internal message')).toBeTruthy()

        rerender(<ThreadTurn {...props} conversationOnly />)
        expect(queryByText('Show 1 internal message')).toBeNull()
        expect(queryByText('Checking the seat history.')).toBeNull()
        expect(getByText('Add two seats.')).toBeTruthy()
    })

    test('the active turn scrolls into view once its messages are in', () => {
        const scrolled: Element[] = []
        jest.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(function (this: Element) {
            scrolled.push(this)
        })
        const props = { onSelectMessage: () => {} }
        const { getByText, rerender } = render(
            <ThreadTurn {...props} turn={{ ...turn, pending: 'loading' }} isActive />
        )
        expect(scrolled).toEqual([])

        rerender(<ThreadTurn {...props} turn={turn} isActive />)
        expect(scrolled).toEqual([getByText('Add two seats.').closest('.ring-1')])

        rerender(<ThreadTurn {...props} turn={turn} isActive conversationOnly />)
        rerender(<ThreadTurn {...props} turn={turn} isActive={false} />)
        expect(scrolled).toHaveLength(1)
        jest.restoreAllMocks()
    })
})
