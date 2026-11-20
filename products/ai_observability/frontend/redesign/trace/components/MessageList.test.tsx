import '@testing-library/jest-dom'

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { ThreadMessage } from '../types'
import { MessageList } from './MessageList'

function textMessage(id: string, text: string): ThreadMessage {
    return { id, role: 'user', parts: [{ kind: 'text', text }], isInternal: false, sourceNodeId: 'gen-1' }
}

const messages = [
    textMessage('m-1', 'Where is my invoice?'),
    textMessage('m-2', 'Let me check.'),
    textMessage('m-3', 'Any news?'),
]

function expandedStates(container: HTMLElement): (string | null)[] {
    return Array.from(container.querySelectorAll('button[aria-expanded]')).map((button) =>
        button.getAttribute('aria-expanded')
    )
}

describe('MessageList', () => {
    it('opens the earlier messages that contain the search, including after the results arrive', () => {
        const { container, rerender } = render(<MessageList messages={messages} emptyText="" openFrom={2} />)
        expect(expandedStates(container)).toEqual(['false', 'false', 'true'])

        rerender(<MessageList messages={messages} emptyText="" openFrom={2} highlightQuery="INVOICE" />)

        expect(expandedStates(container)).toEqual(['true', 'false', 'true'])
    })

    it('cuts a message taller than the window behind Show more, and shows a search match in full', () => {
        const height = jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(window.innerHeight + 1)
        try {
            const { rerender } = render(<MessageList messages={messages} emptyText="" openFrom={0} />)
            expect(screen.getAllByText('Show more')).toHaveLength(3)

            rerender(<MessageList messages={messages} emptyText="" openFrom={0} highlightQuery="invoice" />)

            expect(screen.getAllByText('Show more')).toHaveLength(2)
        } finally {
            height.mockRestore()
        }
    })

    it('shows a cut message in full when a folded tool result in it opens', async () => {
        const height = jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(window.innerHeight + 1)
        try {
            const longResult = Array.from({ length: 12 }, (_, index) => ({ row: index }))
            const toolMessage: ThreadMessage = {
                id: 'm-tool',
                role: 'assistant',
                parts: [{ kind: 'toolCall', name: 'lookup_rows', args: {}, result: longResult }],
                isInternal: true,
                sourceNodeId: 'gen-1',
            }
            const { container } = render(<MessageList messages={[toolMessage]} emptyText="" openFrom={0} />)
            const view = within(container)
            expect(view.getByText('Show more')).toBeInTheDocument()

            fireEvent.click(view.getByText(/^\[\{"row":0\}/))

            await waitFor(() => expect(view.getByText('Show less')).toBeInTheDocument())
        } finally {
            height.mockRestore()
        }
    })
})
