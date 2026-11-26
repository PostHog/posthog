import { cleanup, fireEvent, render } from '@testing-library/react'

import { withTimezone } from '../../shared/testTimezone'
import { ConversationTurn, ThreadMessage } from '../types'
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

    test.each([
        ['as plain text', 'Why did my invoice go up?', 'Why did my invoice go up?'],
        ['as its fields', { question: 'Why did my invoice go up?' }, 'question'],
        ['as the text it is when the text holds JSON', '{"question": "Why?"}', '{"question": "Why?"}'],
        ['as nothing captured when it is an empty list', [], 'Nothing captured.'],
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
        input: { kind: 'json', value: { filters: { types: ['invoice'] } } },
    }

    test.each([
        ['cuts a bubble taller than the window', turn, window.innerHeight + 1, null, 2],
        ['shows a bubble that holds the search query in full', turn, window.innerHeight + 1, 'seats', 0],
        ['cuts a JSON side once however deep it nests', jsonTurn, window.innerHeight + 1, null, 2],
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

    test('keeps message text out of autocapture', () => {
        const { getByText } = render(<ThreadTurn turn={turn} isActive={false} onSelectMessage={() => {}} />)

        expect(getByText('Add two seats.').closest('.ph-no-capture')).not.toBeNull()
        expect(document.querySelector('.ph-no-capture [data-attr]')).toBeNull()
    })

    describe('timing', () => {
        const timed = (waitMs: number | null, waitSlow = false): JSX.Element => (
            <ThreadTurn turn={{ ...turn, waitMs, waitSlow }} isActive={false} onSelectMessage={() => {}} showTiming />
        )

        test('shows timing beside the user message', () => {
            const { getByText } = render(timed(2_100))

            expect(getByText(/10:15/)).toBeTruthy()
            expect(getByText(/2\.1s/)).toBeTruthy()
        })

        test.each([true, false])('marks the wait as slow only when the turn says so: %s', (waitSlow) => {
            const { getByText } = render(timed(2_100, waitSlow))

            expect(getByText(/\ds$/).className.includes('text-warning')).toBe(waitSlow)
        })

        test("shows the clock time in the viewer's timezone", () => {
            withTimezone('America/New_York', () => {
                const { getByText } = render(timed(null))

                expect(getByText(/6:15/)).toBeTruthy()
            })
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

        const unread = (sidesStatus: ConversationTurn['sidesStatus']): ConversationTurn => ({
            ...turn,
            input: { kind: 'messages', messages: [] },
            output: { kind: 'messages', messages: [] },
            sidesStatus,
        })

        test('shows placeholders while its messages load', () => {
            const { container, queryByText } = render(
                <ThreadTurn turn={unread('loading')} isActive={false} onSelectMessage={() => {}} />
            )

            expect(container.querySelectorAll('.LemonSkeleton').length).toBeGreaterThan(0)
            expect(queryByText(/messages/)).toBeNull()
        })

        test.each([
            ['failed', 'error', "Couldn't load this turn's messages.", 'Retry', 1, []],
            [
                'read with nothing in it',
                'ready',
                'This turn has no messages to show.',
                'Open trace',
                0,
                [['trace-1', 'trace-1']],
            ],
        ] as const)(
            'says its messages %s and offers the next step',
            (_name, sidesStatus, notice, button, retries, opened) => {
                const onSelectMessage = jest.fn()
                const onRetrySides = jest.fn()
                const { container, getByText } = render(
                    <ThreadTurn
                        turn={unread(sidesStatus)}
                        isActive={false}
                        onSelectMessage={onSelectMessage}
                        onRetrySides={onRetrySides}
                    />
                )

                expect(getByText(notice)).toBeTruthy()
                expect(container.querySelector('.LemonSkeleton')).toBeNull()
                fireEvent.click(getByText(button))
                expect([onRetrySides.mock.calls.length, onSelectMessage.mock.calls]).toEqual([retries, opened])
            }
        )
    })

    test('the toggle names the roles of the internal messages, and conversation only hides both', () => {
        const hidden = (id: string, role: 'assistant' | 'tool'): ThreadMessage => ({
            id,
            role,
            parts: [{ kind: 'text', text: id }],
            isInternal: true,
            sourceNodeId: 'gen-1',
        })
        const output = {
            kind: 'messages' as const,
            messages: [hidden('seat-lookup', 'tool'), hidden('plan', 'assistant')],
        }
        const props = { turn: { ...turn, output }, isActive: false, onSelectMessage: () => {} }
        const toggle = (container: HTMLElement): string | null | undefined =>
            container.querySelector('[data-attr="trace-view-toggle-hidden-messages"]')?.textContent?.replace(/\s/g, ' ')
        const { container, getByText, queryByText, rerender } = render(<ThreadTurn {...props} />)
        expect(toggle(container)).toEqual('Show 3 internal messages· reasoning and tool calls, tool results')

        rerender(<ThreadTurn {...props} conversationOnly />)
        expect(toggle(container)).toBeUndefined()
        expect(queryByText('Checking the seat history.')).toBeNull()
        expect(getByText('Add two seats.')).toBeTruthy()
    })

    const totals = {
        costUsd: null,
        inputTokens: 2_100,
        outputTokens: 474,
        cacheReadTokens: null,
        cacheWriteTokens: null,
        latencyMs: 1_840,
    }

    test.each<[string, ConversationTurn['trace'], string]>([
        ['its name, latency and tokens', { name: 'rag-query', totals }, 'rag-query · 1.84s · 2,574 tok'],
        [
            'only the parts it has',
            { name: null, totals: { ...totals, inputTokens: null, outputTokens: null } },
            '1.84s',
        ],
    ])('the chip under the answer shows %s, and opens the trace in either mode', (_name, trace, text) => {
        const onSelectMessage = jest.fn()
        const { container } = render(
            <ThreadTurn turn={{ ...turn, trace }} isActive={false} onSelectMessage={onSelectMessage} conversationOnly />
        )
        const chip = container.querySelector<HTMLElement>('[data-attr="trace-view-thread-open-turn-trace"]')

        expect(chip?.textContent).toContain(text)
        expect(chip?.querySelector('.ph-no-capture')?.textContent ?? null).toEqual(trace?.name ?? null)
        fireEvent.click(chip ?? container)
        expect(onSelectMessage).toHaveBeenCalledWith('trace-1', 'trace-1')
    })

    test('a turn scrolls into view once when it becomes active', () => {
        const scrolled: Element[] = []
        jest.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(function (this: Element) {
            scrolled.push(this)
        })
        const props = { onSelectMessage: () => {} }
        const { getByText, rerender } = render(<ThreadTurn {...props} turn={turn} isActive={false} />)
        expect(scrolled).toEqual([])

        rerender(<ThreadTurn {...props} turn={turn} isActive />)
        expect(scrolled).toEqual([getByText('Add two seats.').closest('.ring-1')])

        rerender(<ThreadTurn {...props} turn={turn} isActive conversationOnly />)
        rerender(<ThreadTurn {...props} turn={turn} isActive={false} />)
        expect(scrolled).toHaveLength(1)
        jest.restoreAllMocks()
    })
})
