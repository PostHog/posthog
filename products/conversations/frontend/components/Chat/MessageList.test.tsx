import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { ChatMessage } from '../../types'
import { MessageList } from './MessageList'

// The real Message pulls in the tiptap-backed Editor exports for markdown and rich content; the
// behavior under test is MessageList's own scroll handling, which only needs a stand-in row.
jest.mock('./Message', () => {
    const React = jest.requireActual<typeof import('react')>('react')
    return {
        Message: ({ message }: { message: ChatMessage }) =>
            React.createElement('div', { 'data-attr': `message-${message.id}` }, message.content),
    }
})

// jsdom has no layout, so the component's "is the reader at the bottom?" arithmetic
// (scrollHeight - scrollTop - clientHeight < 120) needs fixed geometry. With these, the reader is
// pinned to the bottom above scrollTop 480 and reading history below it.
const SCROLL_HEIGHT = 1000
const CLIENT_HEIGHT = 400
const AT_BOTTOM = 600
const SCROLLED_UP = 100

const PILL = 'See new messages'

function message(id: string, createdAt: string): ChatMessage {
    return {
        id,
        content: `Message ${id}`,
        authorType: 'customer',
        authorName: 'Customer',
        createdAt,
    }
}

const FIRST = message('1', '2026-01-01T00:00:00Z')
const SECOND = message('2', '2026-01-01T00:01:00Z')
const OLDER = message('0', '2025-12-31T00:00:00Z')

function scrollContainer(): HTMLElement {
    return screen.getByTestId('message-list-scroll')
}

/** Move the reader and fire the scroll event the component listens for. */
function scrollTo(top: number): void {
    const container = scrollContainer()
    container.scrollTop = top
    fireEvent.scroll(container)
}

let scrollToSpy: jest.Mock

describe('MessageList', () => {
    beforeEach(() => {
        scrollToSpy = jest.fn()
        Element.prototype.scrollTo = scrollToSpy
        Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
            configurable: true,
            get: () => SCROLL_HEIGHT,
        })
        Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
            configurable: true,
            get: () => CLIENT_HEIGHT,
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('opens the thread at the latest message when content first loads', () => {
        render(<MessageList messages={[FIRST]} messagesLoading={false} />)

        expect(scrollToSpy).toHaveBeenCalledWith({ top: SCROLL_HEIGHT, behavior: 'instant' })
        expect(screen.queryByText(PILL)).not.toBeInTheDocument()
    })

    it('follows the tail when a new message arrives while the reader is at the bottom', () => {
        const { rerender } = render(<MessageList messages={[FIRST]} messagesLoading={false} />)
        scrollTo(AT_BOTTOM)
        scrollToSpy.mockClear()

        rerender(<MessageList messages={[FIRST, SECOND]} messagesLoading={false} />)

        expect(scrollToSpy).toHaveBeenCalledWith({ top: SCROLL_HEIGHT, behavior: 'smooth' })
        expect(screen.queryByText(PILL)).not.toBeInTheDocument()
    })

    it('holds position and offers the pill when a message arrives after the reader scrolls up', () => {
        const { rerender } = render(<MessageList messages={[FIRST]} messagesLoading={false} />)
        scrollTo(SCROLLED_UP)
        scrollToSpy.mockClear()

        rerender(<MessageList messages={[FIRST, SECOND]} messagesLoading={false} />)

        expect(scrollToSpy).not.toHaveBeenCalled()
        expect(screen.getByText(PILL)).toBeInTheDocument()
    })

    // The regression this PR exists for: agent reports load on their own async request, so one can
    // land long after the messages have settled and must not yank a reader out of history.
    it('holds position and offers the pill when an agent report arrives after the reader scrolls up', () => {
        const { rerender } = render(<MessageList messages={[FIRST]} messagesLoading={false} extras={[]} />)
        scrollTo(SCROLLED_UP)
        scrollToSpy.mockClear()

        rerender(
            <MessageList
                messages={[FIRST]}
                messagesLoading={false}
                extras={[{ at: '2026-01-01T00:02:00Z', element: <div key="report">Agent report</div> }]}
            />
        )

        expect(scrollToSpy).not.toHaveBeenCalled()
        expect(screen.getByText(PILL)).toBeInTheDocument()
    })

    it('does not offer the pill when older messages are prepended', () => {
        const { rerender } = render(<MessageList messages={[FIRST]} messagesLoading={false} />)
        scrollTo(SCROLLED_UP)
        scrollToSpy.mockClear()

        // "Load older" grows messages.length but leaves the newest message unchanged.
        rerender(<MessageList messages={[OLDER, FIRST]} messagesLoading={false} />)

        expect(scrollToSpy).not.toHaveBeenCalled()
        expect(screen.queryByText(PILL)).not.toBeInTheDocument()
    })

    it('jumps to the latest and dismisses the pill when it is clicked', () => {
        const { rerender } = render(<MessageList messages={[FIRST]} messagesLoading={false} />)
        scrollTo(SCROLLED_UP)
        rerender(<MessageList messages={[FIRST, SECOND]} messagesLoading={false} />)
        scrollToSpy.mockClear()

        fireEvent.click(screen.getByText(PILL))

        expect(scrollToSpy).toHaveBeenCalledWith({ top: SCROLL_HEIGHT, behavior: 'smooth' })
        expect(screen.queryByText(PILL)).not.toBeInTheDocument()
    })

    it('dismisses the pill once the reader scrolls back to the bottom themselves', () => {
        const { rerender } = render(<MessageList messages={[FIRST]} messagesLoading={false} />)
        scrollTo(SCROLLED_UP)
        rerender(<MessageList messages={[FIRST, SECOND]} messagesLoading={false} />)
        expect(screen.getByText(PILL)).toBeInTheDocument()

        scrollTo(AT_BOTTOM)

        expect(screen.queryByText(PILL)).not.toBeInTheDocument()
    })
})
