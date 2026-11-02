import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

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
        const { container, rerender } = render(<MessageList messages={messages} emptyText="" defaultOpen="last" />)
        expect(expandedStates(container)).toEqual(['false', 'false', 'true'])

        rerender(<MessageList messages={messages} emptyText="" defaultOpen="last" highlightQuery="INVOICE" />)

        expect(expandedStates(container)).toEqual(['true', 'false', 'true'])
    })
})
