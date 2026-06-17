import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import type { PermissionRequestRecord, ToolInvocation } from '../types/sandboxStreamTypes'
import { SandboxModeBadge } from './InputFormArea'
import { SandboxPermissionInput } from './SandboxPermissionInput'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('use-resize-observer', () => () => ({
    height: 160,
    ref: { current: null },
}))

jest.mock('../maxThreadLogic', () => ({
    maxThreadLogic: { __mock: 'maxThreadLogic' },
}))

jest.mock('../sandboxStreamLogic', () => ({
    // Keyed logic — the component binds it with `sandboxStreamLogic({ streamKey })`.
    sandboxStreamLogic: jest.fn(() => ({ __mock: 'sandboxStreamLogicInstance' })),
}))

jest.mock('../MarkdownMessage', () => ({
    MarkdownMessage: ({ content }: { content: string }) => <div data-attr="markdown">{content}</div>,
}))

const rawToolCall: ToolInvocation = {
    toolCallId: 'tc-1',
    rawServerName: 'posthog',
    rawToolName: 'exec',
    resolvedKey: 'insight-create',
    input: {},
    status: 'pending',
    contentBlocks: [],
}

function makeRequest(overrides: Partial<PermissionRequestRecord> = {}): PermissionRequestRecord {
    return {
        requestId: 'req-1',
        toolCallId: 'tc-1',
        toolName: 'mcp__posthog__exec',
        title: 'Create insight',
        description: 'The agent wants to create an insight.',
        options: [
            { optionId: 'opt-allow', name: 'Approve', kind: 'allow_once' },
            { optionId: 'opt-reject', name: 'Decline', kind: 'reject' },
            { optionId: 'opt-feedback', name: 'Decline with feedback', kind: 'reject_with_feedback' },
        ],
        rawToolCall,
        ...overrides,
    }
}

describe('Sandbox approval input area', () => {
    const respondToPermission = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({ respondToPermission })
        ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: false, currentMode: null })
    })

    afterEach(() => {
        cleanup()
    })

    describe('SandboxPermissionInput', () => {
        it('renders one button per non-feedback option plus the feedback toggle', () => {
            render(<SandboxPermissionInput streamKey="conv-1" request={makeRequest()} />)

            expect(screen.getByText('Approval required')).toBeInTheDocument()
            expect(screen.getByText('Approve')).toBeInTheDocument()
            expect(screen.getByText('Decline')).toBeInTheDocument()
            // reject_with_feedback is feedback-only: it's the toggle that opens the text field, not a plain button.
            expect(screen.getByText('Decline with feedback')).toBeInTheDocument()
        })

        it('posts the chosen optionId on click', () => {
            render(<SandboxPermissionInput streamKey="conv-1" request={makeRequest()} />)

            fireEvent.click(screen.getByText('Approve'))

            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'req-1',
                optionId: 'opt-allow',
            })
        })

        it('guards against double-submit while the reply POST is in flight', () => {
            // The logic's respondingToPermission flag drives the loading state — it flips
            // synchronously on dispatch and resets on success and on failure alike.
            ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: true })
            render(<SandboxPermissionInput streamKey="conv-1" request={makeRequest()} />)

            // Loading message replaces the option list, so nothing can be clicked.
            expect(screen.getByText('Sending response...')).toBeInTheDocument()
            expect(screen.queryByText('Approve')).not.toBeInTheDocument()
            expect(screen.queryByText('Decline')).not.toBeInTheDocument()
            expect(respondToPermission).not.toHaveBeenCalled()
        })

        it('sends feedback text through the reject_with_feedback option', () => {
            render(<SandboxPermissionInput streamKey="conv-1" request={makeRequest()} />)

            // Open the feedback text field via the feedback-only decline toggle.
            fireEvent.click(screen.getByText('Decline with feedback'))
            const input = screen.getByPlaceholderText("Explain what you'd like instead...")
            fireEvent.change(input, { target: { value: 'Use a funnel instead' } })
            fireEvent.click(screen.getByRole('button', { name: 'Send' }))

            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'req-1',
                optionId: 'opt-feedback',
                customInput: 'Use a funnel instead',
            })
        })

        it('renders reject_once as a one-click decline with no feedback toggle', () => {
            const request = makeRequest({
                options: [
                    { optionId: 'opt-allow', name: 'Yes', kind: 'allow_once' },
                    { optionId: 'opt-reject', name: 'No', kind: 'reject_once', customInput: true },
                ],
            })
            render(<SandboxPermissionInput streamKey="conv-1" request={request} />)

            // No optional-feedback affordance — the decline is a plain one-click button.
            expect(screen.queryByText('Add feedback…')).not.toBeInTheDocument()
            fireEvent.click(screen.getByText('No'))
            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'req-1',
                optionId: 'opt-reject',
            })
        })

        it.each([
            [
                'the agent is in plan mode',
                (): void => {
                    ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: false, currentMode: 'plan' })
                },
                makeRequest(),
            ],
            [
                'the tool call is tagged as a plan',
                (): void => {},
                makeRequest({ rawToolCall: { ...rawToolCall, kind: 'plan' } }),
            ],
        ])('shows plan copy when %s', (_case, arrange, request) => {
            arrange()
            render(<SandboxPermissionInput streamKey="conv-1" request={request} />)

            expect(screen.getByText('Approve this plan?')).toBeInTheDocument()
        })

        it('does not show plan copy just because the title mentions a plan', () => {
            render(
                <SandboxPermissionInput
                    streamKey="conv-1"
                    request={makeRequest({ title: 'Create a data retention plan' })}
                />
            )

            expect(screen.getByText('Approval required')).toBeInTheDocument()
        })

        it('falls back to showing every option when filtering would leave none', () => {
            render(
                <SandboxPermissionInput
                    streamKey="conv-1"
                    request={makeRequest({
                        options: [{ optionId: 'opt-always', name: '', kind: 'allow_always' }],
                    })}
                />
            )

            expect(screen.getByText('Approve always')).toBeInTheDocument()
        })
    })

    describe('SandboxModeBadge', () => {
        it.each([
            ['sandbox', 'plan', 'Plan mode'],
            ['sandbox', 'default', 'Default mode'],
        ])('renders the %s runtime in %s mode as a badge', (runtime, mode, label) => {
            ;(useValues as jest.Mock).mockReturnValue({
                conversation: { agent_runtime: runtime },
                sandboxCurrentMode: mode,
            })

            render(<SandboxModeBadge />)

            expect(screen.getByText(label)).toBeInTheDocument()
        })

        it.each([
            ['no mode has been reported', 'sandbox', null],
            ['the conversation is not sandbox-runtime', 'langgraph', 'plan'],
        ])('renders nothing when %s', (_case, runtime, mode) => {
            ;(useValues as jest.Mock).mockReturnValue({
                conversation: { agent_runtime: runtime },
                sandboxCurrentMode: mode,
            })

            const { container } = render(<SandboxModeBadge />)
            expect(container).toBeEmptyDOMElement()
        })
    })
})
