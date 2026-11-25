import { cleanup, render } from '@testing-library/react'

import type { ConversationTurn } from '../../trace/types'
import type { ConversationEdge } from '../types'
import { SessionConversation, type SessionConversationProps } from './SessionConversation'

function nearEnd(): IntersectionObserverEntry {
    const rect = document.body.getBoundingClientRect()
    return {
        isIntersecting: true,
        intersectionRatio: 1,
        boundingClientRect: rect,
        intersectionRect: rect,
        rootBounds: null,
        target: document.body,
        time: 0,
    }
}

describe('SessionConversation', () => {
    const observers = jest.mocked(IntersectionObserver)

    afterEach(cleanup)

    const TURN: ConversationTurn = {
        id: 'trace-1',
        timestamp: '2026-09-01T10:15:00Z',
        waitMs: null,
        error: null,
        input: { kind: 'messages', messages: [] },
        output: { kind: 'messages', messages: [] },
        sidesStatus: 'loading',
    }

    function props(newerEdge: ConversationEdge, onLoadNewer: () => void): SessionConversationProps {
        return {
            status: 'ready',
            turns: [TURN],
            activeTurnId: null,
            olderEdge: 'end',
            newerEdge,
            conversationOnly: false,
            onSelectMessage: () => {},
            onLoadOlder: () => {},
            onLoadNewer,
            onReload: () => {},
            onRetrySides: () => {},
        }
    }

    function scrollNearEnd(): void {
        const latest = observers.mock.calls.length - 1
        const [callback] = observers.mock.calls[latest]
        callback([nearEnd()], observers.mock.results[latest].value)
    }

    it('loads newer turns when the end comes near, and again once the read in flight lands', () => {
        const onLoadNewer = jest.fn()
        const { rerender } = render(<SessionConversation {...props('more', onLoadNewer)} />)

        scrollNearEnd()
        expect(onLoadNewer).toHaveBeenCalledTimes(1)

        const observersBefore = observers.mock.calls.length
        rerender(<SessionConversation {...props('waiting', onLoadNewer)} />)
        expect(observers.mock.calls).toHaveLength(observersBefore)

        // A new observer reports whether the end is near on its first check, so a short page keeps loading.
        rerender(<SessionConversation {...props('more', onLoadNewer)} />)
        expect(observers.mock.calls).toHaveLength(observersBefore + 1)
        scrollNearEnd()
        expect(onLoadNewer).toHaveBeenCalledTimes(2)
    })

    it.each<[string, ConversationEdge, ConversationEdge, boolean, boolean]>([
        ['turns after it', 'end', 'more', false, true],
        ['turns before it', 'more', 'end', true, false],
    ])(
        'a page with no turns and %s keeps loading instead of showing as empty',
        (_name, olderEdge, newerEdge, older, newer) => {
            const onLoadNewer = jest.fn()
            const observersBefore = observers.mock.calls.length
            const { container, queryByText } = render(
                <SessionConversation {...props(newerEdge, onLoadNewer)} turns={[]} olderEdge={olderEdge} />
            )

            expect(queryByText('No turns to show')).toBeNull()
            expect(queryByText(/This session has no messages to show/)).toBeNull()
            expect(!!container.querySelector('[data-attr="ai-observability-session-conversation-load-older"]')).toBe(
                older
            )
            expect(observers.mock.calls.length > observersBefore).toBe(newer)
        }
    )

    it.each<[string, Partial<SessionConversationProps>, string]>([
        ['with no page left to read is empty', { turns: [] }, 'No turns to show'],
        ['the read does not find is not found', { status: 'not_found', turns: [] }, 'Session not found'],
    ])('a session %s', (_name, overrides, title) => {
        const { getByText, queryByText } = render(<SessionConversation {...props('end', () => {})} {...overrides} />)

        expect(getByText(title)).toBeTruthy()
        expect(queryByText('Retry')).toBeNull()
    })
})
