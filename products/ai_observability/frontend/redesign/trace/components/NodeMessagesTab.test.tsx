import '@testing-library/jest-dom'

import { fireEvent, render, within } from '@testing-library/react'

import type { TraceNodeContentApi } from '../../../generated/api.schemas'
import { makeMessage, makeNodeDetail } from '../testFixtures'
import { MessageRole, MessagesOpening, ThreadMessage } from '../types'
import { NodeMessagesTab } from './NodeMessagesTab'

function message(id: string, role: MessageRole): ThreadMessage {
    return makeMessage({ id, role })
}

const content: TraceNodeContentApi = {
    input: {
        kind: 'messages',
        messages: [message('ask-1', 'user'), message('answer-1', 'assistant'), message('ask-2', 'user')],
    },
    output: { kind: 'messages', messages: [message('answer-2', 'assistant')] },
}

function openStates(container: HTMLElement): string {
    return Array.from(container.querySelectorAll('[data-attr="trace-view-message-toggle"]'))
        .map((toggle) => (toggle.getAttribute('aria-expanded') === 'true' ? '1' : '0'))
        .join('')
}

function renderTab(
    opening: MessagesOpening,
    onOpeningChange: jest.Mock,
    shown: TraceNodeContentApi = content
): ReturnType<typeof render> {
    return render(
        <NodeMessagesTab
            stepId="gen-1"
            load={{ status: 'ready', node: makeNodeDetail({ id: 'gen-1', content: shown }) }}
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

    it('renders a conversation beside JSON input without the opening switch, which only moves the input', () => {
        const { container } = renderTab('everything', jest.fn(), {
            input: { kind: 'json', value: { question: 'Why did my invoice go up?' } },
            output: { kind: 'messages', messages: [message('answer-2', 'assistant')] },
        })

        const view = within(container)
        expect(view.getByText('question')).toBeInTheDocument()
        expect(view.getByText('answer-2')).toBeInTheDocument()
        expect(openStates(container)).toEqual('1')
        expect(container.querySelector('[data-attr="trace-view-messages-opening-last-turn"]')).not.toBeInTheDocument()
    })

    it('keeps a JSON side as it was when the opening changes', () => {
        const mixed: TraceNodeContentApi = {
            input: content.input,
            output: { kind: 'json', value: { question: 'Why did my invoice go up?' } },
        }
        const onOpeningChange = jest.fn()
        const { container } = renderTab('lastTurn', onOpeningChange, mixed)
        fireEvent.click(container.querySelector('[data-attr="trace-view-io-json"]')!)
        expect(within(container).queryByText('question')).not.toBeInTheDocument()

        fireEvent.click(container.querySelector('[data-attr="trace-view-messages-opening-last-turn"]')!)

        expect(within(container).queryByText('question')).not.toBeInTheDocument()
        expect(within(container).getByText(/"question"/)).toBeInTheDocument()
    })

    it('hides the opening switch when neither side is messages', () => {
        const { container } = renderTab('lastTurn', jest.fn(), {
            input: { kind: 'json', value: { question: 'Why did my invoice go up?' } },
            output: { kind: 'json', value: { hits: 3 } },
        })

        expect(within(container).getByText('hits')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="trace-view-messages-opening-last-turn"]')).not.toBeInTheDocument()
    })
})
