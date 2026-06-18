import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { McpToolCallMessage } from '../../maxTypes'
import { SandboxToolActivity } from './SandboxActivity'

function expectBefore(first: HTMLElement, second: HTMLElement): void {
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
}

function makeMessage(overrides: Partial<McpToolCallMessage> = {}): McpToolCallMessage {
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
