import {
    AssistantMessage,
    AssistantMessageType,
    AssistantToolCallMessage,
    RootAssistantMessage,
} from '~/queries/schema/schema-assistant-messages'

import { EnhancedToolCall } from './max-constants'
import { findPendingClientToolCall, isMultiQuestionFormMessage, threadEndsWithMultiQuestionForm } from './utils'

describe('max/utils', () => {
    describe('isMultiQuestionFormMessage()', () => {
        it('returns true for AssistantMessage with create_form tool call', () => {
            const message = {
                type: AssistantMessageType.Assistant,
                content: 'Please answer these questions',
                tool_calls: [
                    {
                        id: 'tc-1',
                        name: 'create_form',
                        args: { questions: [] },
                        type: 'tool_call' as const,
                    },
                ],
            } as unknown as AssistantMessage & { tool_calls: EnhancedToolCall[] }
            expect(isMultiQuestionFormMessage(message)).toBe(true)
        })

        it('returns false for AssistantMessage without tool calls', () => {
            const message = {
                type: AssistantMessageType.Assistant,
                content: 'Just a regular message',
            } as unknown as AssistantMessage
            expect(isMultiQuestionFormMessage(message)).toBe(false)
        })

        it('returns false for AssistantMessage with other tool calls', () => {
            const message = {
                type: AssistantMessageType.Assistant,
                content: 'Using a different tool',
                tool_calls: [
                    {
                        id: 'tc-1',
                        name: 'search',
                        args: {},
                        type: 'tool_call' as const,
                    },
                ],
            } as unknown as AssistantMessage & { tool_calls: EnhancedToolCall[] }
            expect(isMultiQuestionFormMessage(message)).toBe(false)
        })

        it('returns false for non-AssistantMessage types', () => {
            const humanMessage = {
                type: AssistantMessageType.Human,
                content: 'Hello',
            } as unknown as AssistantMessage & { tool_calls: EnhancedToolCall[] }
            expect(isMultiQuestionFormMessage(humanMessage)).toBe(false)

            const toolCallMessage = {
                type: AssistantMessageType.ToolCall,
                content: 'Tool result',
                tool_call_id: 'tc-1',
            } as unknown as AssistantToolCallMessage
            expect(isMultiQuestionFormMessage(toolCallMessage)).toBe(false)
        })

        it('returns false for null or undefined', () => {
            expect(isMultiQuestionFormMessage(null)).toBe(false)
            expect(isMultiQuestionFormMessage(undefined)).toBe(false)
        })

        it('returns true when one of multiple tool calls is create_form', () => {
            const message = {
                type: AssistantMessageType.Assistant,
                content: 'Multiple tools',
                tool_calls: [
                    {
                        id: 'tc-1',
                        name: 'search',
                        args: { query: 'test' },
                        type: 'tool_call' as const,
                    },
                    {
                        id: 'tc-2',
                        name: 'create_form',
                        args: { questions: [] },
                        type: 'tool_call' as const,
                    },
                    {
                        id: 'tc-3',
                        name: 'analyze',
                        args: {},
                        type: 'tool_call' as const,
                    },
                ],
            } as unknown as AssistantMessage & { tool_calls: EnhancedToolCall[] }
            expect(isMultiQuestionFormMessage(message)).toBe(true)
        })

        it('returns false for empty tool_calls array', () => {
            const message = {
                type: AssistantMessageType.Assistant,
                content: 'No tools',
                tool_calls: [],
            } as unknown as AssistantMessage & { tool_calls: EnhancedToolCall[] }
            expect(isMultiQuestionFormMessage(message)).toBe(false)
        })
    })

    describe('threadEndsWithMultiQuestionForm()', () => {
        // With NodeInterrupt(None), the thread ends with the AssistantMessage containing
        // the create_form tool call - no ToolCall message is created

        it('returns true when last message is AssistantMessage with create_form tool call', () => {
            const messages = [
                {
                    type: AssistantMessageType.Human,
                    content: 'Hello',
                },
                {
                    type: AssistantMessageType.Assistant,
                    content: 'Please answer:',
                    tool_calls: [
                        {
                            id: 'tc-1',
                            name: 'create_form',
                            args: { questions: [] },
                            type: 'tool_call' as const,
                        },
                    ],
                },
            ] as unknown as RootAssistantMessage[]
            expect(threadEndsWithMultiQuestionForm(messages)).toBe(true)
        })

        it('returns false for empty thread', () => {
            expect(threadEndsWithMultiQuestionForm([])).toBe(false)
        })

        it('returns false when last message is AssistantMessage without tool calls', () => {
            const messages = [
                {
                    type: AssistantMessageType.Human,
                    content: 'Hello',
                },
                {
                    type: AssistantMessageType.Assistant,
                    content: 'Hi there!',
                },
            ] as unknown as RootAssistantMessage[]
            expect(threadEndsWithMultiQuestionForm(messages)).toBe(false)
        })

        it('returns false when last message is a ToolCall response (form already answered)', () => {
            const messages = [
                {
                    type: AssistantMessageType.Assistant,
                    content: 'Please answer:',
                    tool_calls: [
                        {
                            id: 'tc-1',
                            name: 'create_form',
                            args: { questions: [] },
                            type: 'tool_call' as const,
                        },
                    ],
                },
                {
                    type: AssistantMessageType.ToolCall,
                    content: 'User answers',
                    tool_call_id: 'tc-1',
                    ui_payload: { create_form: { answers: { q1: 'answer1' } } },
                },
            ] as unknown as RootAssistantMessage[]
            expect(threadEndsWithMultiQuestionForm(messages)).toBe(false)
        })

        it('returns false when last message is AssistantMessage with non-create_form tool call', () => {
            const messages = [
                {
                    type: AssistantMessageType.Human,
                    content: 'Hello',
                },
                {
                    type: AssistantMessageType.Assistant,
                    content: 'Using search',
                    tool_calls: [
                        {
                            id: 'tc-1',
                            name: 'search',
                            args: {},
                            type: 'tool_call' as const,
                        },
                    ],
                },
            ] as unknown as RootAssistantMessage[]
            expect(threadEndsWithMultiQuestionForm(messages)).toBe(false)
        })

        it('returns false when last message is HumanMessage', () => {
            const messages = [
                {
                    type: AssistantMessageType.Assistant,
                    content: 'Hi',
                },
                {
                    type: AssistantMessageType.Human,
                    content: 'Hello',
                },
            ] as unknown as RootAssistantMessage[]
            expect(threadEndsWithMultiQuestionForm(messages)).toBe(false)
        })
    })

    describe('findPendingClientToolCall()', () => {
        const clientToolNames = new Set(['my_client_tool'])

        const humanMessage = (content: string): RootAssistantMessage =>
            ({ type: AssistantMessageType.Human, content }) as unknown as RootAssistantMessage

        const toolResultMessage = (toolCallId: string): RootAssistantMessage =>
            ({
                type: AssistantMessageType.ToolCall,
                tool_call_id: toolCallId,
                content: 'done',
            }) as unknown as RootAssistantMessage

        const assistantMessageWithCall = (id: string, name = 'my_client_tool'): RootAssistantMessage =>
            ({
                type: AssistantMessageType.Assistant,
                content: '',
                tool_calls: [{ id, name, args: { payload: 'data' } }],
            }) as unknown as RootAssistantMessage

        it('finds a dangling client tool call at the end of the thread', () => {
            const pending = findPendingClientToolCall([assistantMessageWithCall('tc-1')], clientToolNames)

            expect(pending).toEqual({
                toolName: 'my_client_tool',
                toolCallId: 'tc-1',
                args: { payload: 'data' },
            })
        })

        it('finds a dangling client tool call even when a sibling tool result lands after it', () => {
            const messages = [
                humanMessage('Set up a parser'),
                assistantMessageWithCall('tc-1'),
                toolResultMessage('tc-other'), // a parallel server-side tool finished after
            ]

            expect(findPendingClientToolCall(messages, clientToolNames)?.toolCallId).toBe('tc-1')
        })

        it('returns null when the client tool call already has a result message', () => {
            const messages = [assistantMessageWithCall('tc-1'), toolResultMessage('tc-1')]

            expect(findPendingClientToolCall(messages, clientToolNames)).toBeNull()
        })

        it('ignores dangling calls from previous turns', () => {
            // An abandoned call followed by a new human message starts a fresh turn.
            const messages = [
                assistantMessageWithCall('tc-1'),
                humanMessage('Never mind, do something else'),
                { type: AssistantMessageType.Assistant, content: 'Sure!' } as unknown as RootAssistantMessage,
            ]

            expect(findPendingClientToolCall(messages, clientToolNames)).toBeNull()
        })

        it('returns null for tools that are not client-executed', () => {
            const messages = [assistantMessageWithCall('tc-2', 'create_form')]

            expect(findPendingClientToolCall(messages, clientToolNames)).toBeNull()
        })

        it('returns null for an empty thread or a thread ending with a human message', () => {
            expect(findPendingClientToolCall([], clientToolNames)).toBeNull()
            expect(findPendingClientToolCall([humanMessage('Hello')], clientToolNames)).toBeNull()
        })
    })
})
