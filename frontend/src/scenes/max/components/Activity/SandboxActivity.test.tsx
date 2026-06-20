import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { SandboxToolCallMessage } from '../../maxTypes'
import { SandboxToolActivity, contentBlockText, renderContentBlocks } from './SandboxActivity'

function expectBefore(first: HTMLElement, second: HTMLElement): void {
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
}

function makeMessage(overrides: Partial<SandboxToolCallMessage> = {}): SandboxToolCallMessage {
    return {
        id: 'tc-1',
        resolvedKey: 'query-trends',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        rawInput: { command: 'call query-trends {"kind":"TrendsQuery","series":[]}' },
        innerToolName: 'query-trends',
        innerInput: { kind: 'TrendsQuery', series: [] },
        content: [],
        status: 'in_progress',
        title: 'Query trends',
        ...overrides,
    }
}

describe('SandboxToolActivity', () => {
    it('renders details before widget children wrapped in a message bubble', () => {
        render(
            <SandboxToolActivity message={makeMessage()}>
                <div data-attr="widget">Visualization</div>
            </SandboxToolActivity>
        )

        const header = screen.getByText('Query trends')
        const input = screen.getByText('Input')
        const widget = screen.getByTestId('widget')
        const bubble = widget.closest('[data-message-type="ai"]')

        expect(bubble).toBeInTheDocument()
        expectBefore(header, input)
        expectBefore(input, bubble as HTMLElement)
    })
})

describe('renderContentBlocks', () => {
    it('unwraps the ACP { type: content, content: { type: text, text } } envelope', () => {
        const blocks = [{ type: 'content', content: { type: 'text', text: 'hello world' } }]
        expect(renderContentBlocks(blocks)).toEqual('hello world')
    })

    it('reads a flat { type: text, text } block directly', () => {
        expect(contentBlockText({ type: 'text', text: 'done' })).toEqual('done')
    })

    it('joins multiple blocks with newlines', () => {
        const blocks = [
            { type: 'content', content: { type: 'text', text: 'one' } },
            { type: 'text', text: 'two' },
        ]
        expect(renderContentBlocks(blocks)).toEqual('one\ntwo')
    })

    it('falls back to pretty JSON for a non-text block', () => {
        const block = { type: 'content', content: { type: 'image', data: 'abc' } }
        expect(contentBlockText(block)).toEqual(JSON.stringify(block, null, 2))
    })
})
