import '@testing-library/jest-dom'

import { fireEvent, render } from '@testing-library/react'

import { MessageRole, MessagesOpening, NodeContent, ThreadMessage } from '../types'
import { NodeMessagesTab } from './NodeMessagesTab'

function message(id: string, role: MessageRole): ThreadMessage {
    return { id, role, parts: [{ kind: 'text', text: id }], isInternal: false, sourceNodeId: 'gen-1' }
}

const content: NodeContent = {
    kind: 'messages',
    input: [message('ask-1', 'user'), message('answer-1', 'assistant'), message('ask-2', 'user')],
    output: [message('answer-2', 'assistant')],
}

function openStates(container: HTMLElement): string {
    return Array.from(container.querySelectorAll('[data-attr="trace-view-message-toggle"]'))
        .map((toggle) => (toggle.getAttribute('aria-expanded') === 'true' ? '1' : '0'))
        .join('')
}

function renderTab(opening: MessagesOpening, onOpeningChange: jest.Mock): ReturnType<typeof render> {
    return render(
        <NodeMessagesTab
            stepId="gen-1"
            content={content}
            error={null}
            onViewInThread={null}
            opening={opening}
            onOpeningChange={onOpeningChange}
        />
    )
}

describe('NodeMessagesTab', () => {
    it('drops messages opened by hand when the selected opening is clicked again', () => {
        const onOpeningChange = jest.fn()
        const { container } = renderTab('lastTurn', onOpeningChange)
        expect(openStates(container)).toEqual('0011')
        expect(container.querySelector('[data-earlier-messages]')).toHaveTextContent('1 earlier turn · 2 messages')

        fireEvent.click(container.querySelector('[data-attr="trace-view-message-toggle"]')!)
        expect(openStates(container)).toEqual('1011')

        fireEvent.click(container.querySelector('[data-attr="trace-view-messages-opening-last-turn"]')!)

        expect(openStates(container)).toEqual('0011')
        expect(onOpeningChange).not.toHaveBeenCalled()
    })
})
