import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { SandboxToolCallMessage } from '../../../maxTypes'
import { BuiltinToolRenderer } from './builtinToolRenderers'
import { GenericMcpToolRenderer } from './GenericMcpToolRenderer'

function textBlock(text: string): unknown {
    return { type: 'content', content: { type: 'text', text } }
}

function imageBlock(data: string, mimeType: string): unknown {
    return { type: 'content', content: { type: 'image', data, mimeType } }
}

function makeMessage(overrides: Partial<SandboxToolCallMessage> = {}): SandboxToolCallMessage {
    return {
        id: 'tc-1',
        resolvedKey: 'Bash',
        rawServerName: 'claude',
        rawToolName: '',
        rawInput: {},
        content: [],
        status: 'completed',
        ...overrides,
    }
}

describe('builtin tool renderers', () => {
    afterEach(() => cleanup())

    it('renders a Bash command in the header and its output on expand', () => {
        render(
            <BuiltinToolRenderer
                isLastInGroup
                message={makeMessage({
                    claudeToolName: 'Bash',
                    resolvedKey: 'Bash',
                    rawInput: { command: 'pnpm build' },
                    content: [textBlock('build succeeded')],
                })}
            />
        )
        expect(screen.getByText('pnpm build')).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByText('build succeeded')).toBeInTheDocument()
    })

    it('summarizes a Read call with its line count and file chip', () => {
        render(
            <BuiltinToolRenderer
                isLastInGroup
                message={makeMessage({
                    claudeToolName: 'Read',
                    resolvedKey: 'Read',
                    locations: [{ path: 'frontend/app.ts' }],
                    content: [textBlock('const a = 1\nconst b = 2')],
                })}
            />
        )
        expect(screen.getByText('Read 2 lines')).toBeInTheDocument()
        expect(screen.getByText('app.ts')).toBeInTheDocument()
    })

    it('previews a Read image', () => {
        render(
            <BuiltinToolRenderer
                isLastInGroup
                message={makeMessage({
                    claudeToolName: 'Read',
                    resolvedKey: 'Read',
                    locations: [{ path: 'shot.png' }],
                    content: [imageBlock('AAAA', 'image/png')],
                })}
            />
        )
        expect(screen.getByText('Read image')).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByAltText('shot.png')).toBeInTheDocument()
    })

    it('counts search results in the header', () => {
        render(
            <BuiltinToolRenderer
                isLastInGroup
                message={makeMessage({
                    claudeToolName: 'Grep',
                    resolvedKey: 'Grep',
                    title: 'Grep TODO',
                    content: [textBlock('a.ts:1\nb.ts:4\nc.ts:9')],
                })}
            />
        )
        expect(screen.getByText('Grep TODO')).toBeInTheDocument()
        expect(screen.getByText('3 results')).toBeInTheDocument()
    })

    it.each([
        ['tools', 'List tools', '__posthog_exec_tools__'],
        ['info execute-sql', 'Read execute-sql', '__posthog_exec_info__'],
        ['schema insight-create field', 'Inspect insight-create.field', '__posthog_exec_schema__'],
        ['bogus', 'Run command', '__posthog_exec_unknown__'],
    ])('labels the PostHog exec verb "%s" as "%s"', (command, label, resolvedKey) => {
        render(
            <BuiltinToolRenderer
                isLastInGroup
                message={makeMessage({
                    resolvedKey,
                    rawServerName: 'posthog',
                    rawToolName: 'exec',
                    rawInput: { command },
                })}
            />
        )
        expect(screen.getByText(label)).toBeInTheDocument()
    })

    it('shows the search regex as the PostHog exec subtitle', () => {
        render(
            <BuiltinToolRenderer
                isLastInGroup
                message={makeMessage({
                    resolvedKey: '__posthog_exec_search__',
                    rawServerName: 'posthog',
                    rawToolName: 'exec',
                    rawInput: { command: 'search funnel' },
                })}
            />
        )
        expect(screen.getByText('Search tools')).toBeInTheDocument()
        expect(screen.getByText('funnel')).toBeInTheDocument()
    })

    it('renders an unmapped MCP tool with a server - tool (MCP) header', () => {
        render(
            <GenericMcpToolRenderer
                isLastInGroup
                message={makeMessage({
                    resolvedKey: 'do_thing',
                    rawServerName: 'user-mcp',
                    rawToolName: 'do_thing',
                    rawInput: { foo: 'bar' },
                })}
            />
        )
        expect(screen.getByText('user-mcp -')).toBeInTheDocument()
        expect(screen.getByText('do_thing')).toBeInTheDocument()
        expect(screen.getByText('(MCP)')).toBeInTheDocument()
    })
})
