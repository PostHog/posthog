import {
    AssistantMessage,
    AssistantMessageType,
    AssistantToolCallMessage,
    RootAssistantMessage,
} from '~/queries/schema/schema-assistant-messages'

import { EnhancedToolCall } from './Thread'
import {
    checkSuggestionRequiresUserInput,
    formatSuggestion,
    isMultiQuestionFormMessage,
    stripSuggestionPlaceholders,
    threadEndsWithMultiQuestionForm,
} from './utils'

describe('max/utils', () => {
    describe('checkSuggestionRequiresUserInput()', () => {
        it('returns true for suggestions with angle brackets', () => {
            expect(checkSuggestionRequiresUserInput('Show me <metric> over time')).toBe(true)
            expect(checkSuggestionRequiresUserInput('Compare <event1> vs <event2>')).toBe(true)
            expect(checkSuggestionRequiresUserInput('Filter by <property>')).toBe(true)
        })

        it('returns true for suggestions with ellipsis', () => {
            expect(checkSuggestionRequiresUserInput('Show me trends for…')).toBe(true)
            expect(checkSuggestionRequiresUserInput('Create a funnel…')).toBe(true)
        })

        it('returns true for suggestions with mixed placeholders', () => {
            expect(checkSuggestionRequiresUserInput('Show <metric> trends for…')).toBe(true)
            expect(checkSuggestionRequiresUserInput('Compare <event> over…')).toBe(true)
        })

        it('returns false for suggestions without placeholders', () => {
            expect(checkSuggestionRequiresUserInput('Show me page views')).toBe(false)
            expect(checkSuggestionRequiresUserInput('Create a simple funnel')).toBe(false)
            expect(checkSuggestionRequiresUserInput('Display user retention')).toBe(false)
        })

        it('handles empty and edge cases', () => {
            expect(checkSuggestionRequiresUserInput('')).toBe(false)
            expect(checkSuggestionRequiresUserInput('No special characters')).toBe(false)
            expect(checkSuggestionRequiresUserInput('Just some text')).toBe(false)
        })
    })

    describe('stripSuggestionPlaceholders()', () => {
        it('removes angle bracket placeholders', () => {
            expect(stripSuggestionPlaceholders('Show me <metric> over time')).toBe('Show me  over time ')
            expect(stripSuggestionPlaceholders('Filter by <property>')).toBe('Filter by ')
        })

        it('handles empty string', () => {
            expect(stripSuggestionPlaceholders('')).toBe(' ')
        })
    })

    describe('formatSuggestion()', () => {
        it('removes angle brackets but keeps content', () => {
            expect(formatSuggestion('Show me <metric> over time')).toBe('Show me metric over time')
            expect(formatSuggestion('Compare <event1> vs <event2>')).toBe('Compare event1 vs event2')
            expect(formatSuggestion('Filter by <property>')).toBe('Filter by property')
        })

        it('preserves ellipsis at the end', () => {
            expect(formatSuggestion('Show me trends for…')).toBe('Show me trends for…')
            expect(formatSuggestion('Create a funnel…')).toBe('Create a funnel…')
        })

        it('handles mixed placeholders', () => {
            expect(formatSuggestion('Show <metric> trends for…')).toBe('Show metric trends for…')
            expect(formatSuggestion('Compare <event> over…')).toBe('Compare event over…')
        })

        it('handles suggestions without placeholders', () => {
            expect(formatSuggestion('Show me page views')).toBe('Show me page views')
            expect(formatSuggestion('Create a simple funnel')).toBe('Create a simple funnel')
        })

        it('trims whitespace', () => {
            expect(formatSuggestion('  Show me data  ')).toBe('Show me data')
            expect(formatSuggestion('  Show <metric>  ')).toBe('Show metric')
            expect(formatSuggestion('  Show data…  ')).toBe('Show data…')
        })

        it('handles empty string', () => {
            expect(formatSuggestion('')).toBe('')
        })
    })

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
})
