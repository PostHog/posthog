import { AssistantMessageType, RootAssistantMessage } from '~/queries/schema/schema-assistant-messages'

import {
    getTicketPromptData,
    getTicketSummaryData,
    isTicketConfirmationMessage,
    wasTicketAISuggested,
} from '../ticketUtils'

type MessageStatus = 'loading' | 'completed' | 'error'
type ThreadMessage = RootAssistantMessage & { status: MessageStatus }

describe('ticketUtils', () => {
    describe('wasTicketAISuggested', () => {
        const createHumanMessage = (content: string): ThreadMessage => ({
            type: AssistantMessageType.Human,
            content,
            status: 'completed',
            id: `human-${Math.random()}`,
        })

        const createAIMessage = (content: string): ThreadMessage => ({
            type: AssistantMessageType.Assistant,
            content,
            status: 'completed',
            id: `ai-${Math.random()}`,
        })

        it.each([
            {
                description: 'returns false when thread is empty',
                thread: [],
                expected: false,
            },
            {
                description: 'returns false when no escalation language is present',
                thread: [
                    createHumanMessage('help'),
                    createAIMessage('I can help you with that'),
                    createHumanMessage('thanks'),
                    createAIMessage('You are welcome'),
                ],
                expected: false,
            },
            {
                description: 'returns true when AI mentions "support ticket"',
                thread: [createHumanMessage('I need help'), createAIMessage('I can help you create a support ticket')],
                expected: true,
            },
            {
                description: 'returns true when AI mentions "contact support"',
                thread: [
                    createHumanMessage('this is broken'),
                    createAIMessage('You may want to contact support about this'),
                ],
                expected: true,
            },
            {
                description: 'returns true when AI mentions "support team"',
                thread: [createHumanMessage('help'), createAIMessage('I recommend reaching out to the support team')],
                expected: true,
            },
            {
                description: 'returns true when AI says "report this"',
                thread: [
                    createHumanMessage('I found a bug'),
                    createAIMessage('This looks like a bug. You should report this.'),
                ],
                expected: true,
            },
            {
                description: 'returns true when user mentions wanting to raise a ticket',
                thread: [
                    createHumanMessage('help'),
                    createAIMessage('Let me look into this'),
                    createHumanMessage('I think I need to raise a ticket about this'),
                ],
                expected: true,
            },
            {
                description: 'matches case-insensitively',
                thread: [createHumanMessage('help'), createAIMessage('You should Contact Support about this')],
                expected: true,
            },
            {
                description: 'scans the last 5 messages',
                thread: [
                    createAIMessage('You should contact support'),
                    createHumanMessage('msg1'),
                    createAIMessage('response1'),
                    createHumanMessage('msg2'),
                    createAIMessage('response2'),
                ],
                expected: true,
            },
            {
                description: 'does not scan beyond the last 5 messages',
                thread: [
                    createAIMessage('You should contact support'),
                    createHumanMessage('msg0'),
                    createAIMessage('response0'),
                    createHumanMessage('msg1'),
                    createAIMessage('response1'),
                    createHumanMessage('msg2'),
                ],
                expected: false,
            },
            {
                description: 'detects escalation in conversations without /ticket command',
                thread: [
                    createHumanMessage('my dashboard is broken'),
                    createAIMessage('I see the issue. You may want to contact support about this.'),
                    createHumanMessage('ok thanks'),
                ],
                expected: true,
            },
        ])('$description', ({ thread, expected }) => {
            expect(wasTicketAISuggested(thread)).toBe(expected)
        })
    })

    describe('getTicketPromptData', () => {
        const createHumanMessage = (content: string): ThreadMessage => ({
            type: AssistantMessageType.Human,
            content,
            status: 'completed',
            id: `human-${Math.random()}`,
        })

        const createAIMessage = (content: string): ThreadMessage => ({
            type: AssistantMessageType.Assistant,
            content,
            status: 'completed',
            id: `ai-${Math.random()}`,
        })

        it.each([
            {
                description: 'returns needed=false when thread has less than 2 messages',
                thread: [createHumanMessage('/ticket')],
                streamingActive: false,
                expected: { needed: false },
            },
            {
                description: 'returns needed=false when streaming is active',
                thread: [createHumanMessage('/ticket'), createAIMessage("I'll help you create a support ticket")],
                streamingActive: true,
                expected: { needed: false },
            },
            {
                description: 'returns needed=true for initial ticket prompt without confirmation',
                thread: [createHumanMessage('/ticket'), createAIMessage("I'll help you create a support ticket")],
                streamingActive: false,
                expected: { needed: true, initialText: undefined },
            },
            {
                description: 'returns needed=true with initialText when ticket has description',
                thread: [
                    createHumanMessage('/ticket My issue description'),
                    createAIMessage("I'll help you create a support ticket"),
                ],
                streamingActive: false,
                expected: { needed: true, initialText: 'My issue description' },
            },
            {
                description: 'returns needed=false when confirmation message exists',
                thread: [
                    createHumanMessage('/ticket'),
                    createAIMessage("I'll help you create a support ticket"),
                    createAIMessage("I've created a support ticket for you"),
                ],
                streamingActive: false,
                expected: { needed: false },
            },
            {
                description: 'returns needed=false when first message is not /ticket',
                thread: [createHumanMessage('hello'), createAIMessage('hi there')],
                streamingActive: false,
                expected: { needed: false },
            },
            {
                description: 'returns needed=false when first message is not human',
                thread: [createAIMessage('hello'), createHumanMessage('/ticket')],
                streamingActive: false,
                expected: { needed: false },
            },
            {
                description: 'returns needed=false when last message is not AI prompt response',
                thread: [
                    createHumanMessage('/ticket'),
                    createAIMessage('some other response'),
                    createHumanMessage('more chat'),
                ],
                streamingActive: false,
                expected: { needed: false },
            },
            {
                description: 'returns initialText=undefined when /ticket has only whitespace after it',
                thread: [createHumanMessage('/ticket   '), createAIMessage("I'll help you create a support ticket")],
                streamingActive: false,
                expected: { needed: true, initialText: undefined },
            },
        ])('$description', ({ thread, streamingActive, expected }) => {
            expect(getTicketPromptData(thread, streamingActive)).toEqual(expected)
        })
    })

    describe('getTicketSummaryData', () => {
        const createHumanMessage = (content: string): ThreadMessage => ({
            type: AssistantMessageType.Human,
            content,
            status: 'completed',
            id: `human-${Math.random()}`,
        })

        const createAIMessage = (content: string): ThreadMessage => ({
            type: AssistantMessageType.Assistant,
            content,
            status: 'completed',
            id: `ai-${Math.random()}`,
        })

        it.each([
            {
                description: 'returns null when thread has less than 3 messages',
                thread: [createHumanMessage('/ticket'), createAIMessage('response')],
                streamingActive: false,
                expected: null,
            },
            {
                description: 'returns null when streaming is active',
                thread: [
                    createHumanMessage('hello'),
                    createAIMessage('hi'),
                    createHumanMessage('/ticket'),
                    createAIMessage('summary'),
                ],
                streamingActive: true,
                expected: null,
            },
            {
                description: 'returns null when no ticket command exists',
                thread: [createHumanMessage('hello'), createAIMessage('hi'), createHumanMessage('more')],
                streamingActive: false,
                expected: null,
            },
            {
                description: 'returns null when ticket command is first message',
                thread: [
                    createHumanMessage('/ticket'),
                    createAIMessage("I'll help you"),
                    createHumanMessage('more info'),
                ],
                streamingActive: false,
                expected: null,
            },
            {
                description: 'returns null when ticket command is last message',
                thread: [createHumanMessage('hello'), createAIMessage('hi'), createHumanMessage('/ticket')],
                streamingActive: false,
                expected: null,
            },
            {
                description: 'returns summary when ticket command has AI response',
                thread: [
                    createHumanMessage('I have an issue'),
                    createAIMessage('Tell me more'),
                    createHumanMessage('/ticket'),
                    createAIMessage('Here is a summary of the issue'),
                ],
                streamingActive: false,
                expected: {
                    summary: 'Here is a summary of the issue',
                    messageIndex: 3,
                },
            },
            {
                description: 'returns null when AI response is the initial ticket prompt',
                thread: [
                    createHumanMessage('hello'),
                    createAIMessage('hi'),
                    createHumanMessage('/ticket'),
                    createAIMessage("I'll help you create a support ticket"),
                ],
                streamingActive: false,
                expected: null,
            },
            {
                description: 'returns discarded when user continued conversation after summary',
                thread: [
                    createHumanMessage('I have an issue'),
                    createAIMessage('Tell me more'),
                    createHumanMessage('/ticket'),
                    createAIMessage('Here is a summary'),
                    createHumanMessage('Actually, I have more to add'),
                ],
                streamingActive: false,
                expected: {
                    discarded: true,
                    messageIndex: 3,
                },
            },
            {
                description: 'returns null when ticket confirmation already exists',
                thread: [
                    createHumanMessage('issue'),
                    createAIMessage('response'),
                    createHumanMessage('/ticket'),
                    createAIMessage('summary'),
                    createAIMessage("I've created a support ticket for you"),
                ],
                streamingActive: false,
                expected: null,
            },
            {
                description: 'combines user text with AI summary when ticket has description',
                thread: [
                    createHumanMessage('I have an issue'),
                    createAIMessage('Tell me more'),
                    createHumanMessage('/ticket My additional notes'),
                    createAIMessage('AI generated summary'),
                ],
                streamingActive: false,
                expected: {
                    summary: 'User notes: My additional notes\n\nAI generated summary',
                    messageIndex: 3,
                },
            },
            {
                description: 'finds last ticket command when multiple exist',
                thread: [
                    createHumanMessage('/ticket first'),
                    createAIMessage('first summary'),
                    createHumanMessage('more chat'),
                    createAIMessage('response'),
                    createHumanMessage('/ticket second'),
                    createAIMessage('second summary'),
                ],
                streamingActive: false,
                expected: {
                    summary: 'User notes: second\n\nsecond summary',
                    messageIndex: 5,
                },
            },
            {
                description: 'returns summary without user text when ticket command has no description',
                thread: [
                    createHumanMessage('issue'),
                    createAIMessage('response'),
                    createHumanMessage('/ticket'),
                    createAIMessage('AI summary'),
                ],
                streamingActive: false,
                expected: {
                    summary: 'AI summary',
                    messageIndex: 3,
                },
            },
            {
                description: 'returns summary when only whitespace follows ticket command',
                thread: [
                    createHumanMessage('issue'),
                    createAIMessage('response'),
                    createHumanMessage('/ticket   '),
                    createAIMessage('AI summary'),
                ],
                streamingActive: false,
                expected: {
                    summary: 'AI summary',
                    messageIndex: 3,
                },
            },
        ])('$description', ({ thread, streamingActive, expected }) => {
            expect(getTicketSummaryData(thread, streamingActive)).toEqual(expected)
        })
    })

    describe('isTicketConfirmationMessage', () => {
        const createHumanMessage = (content: string): ThreadMessage => ({
            type: AssistantMessageType.Human,
            content,
            status: 'completed',
            id: `human-${Math.random()}`,
        })

        const createAIMessage = (content: string): ThreadMessage => ({
            type: AssistantMessageType.Assistant,
            content,
            status: 'completed',
            id: `ai-${Math.random()}`,
        })

        it.each([
            {
                description: 'returns true for AI message with confirmation text',
                message: createAIMessage("I've created a support ticket for you"),
                expected: true,
            },
            {
                description: 'returns true when confirmation text is in middle of message',
                message: createAIMessage("Great! I've created a support ticket for you. Here are the details."),
                expected: true,
            },
            {
                description: 'returns false for human message with confirmation text',
                message: createHumanMessage("I've created a support ticket for you"),
                expected: false,
            },
            {
                description: 'returns false for AI message without confirmation text',
                message: createAIMessage('Here is a summary of your issue'),
                expected: false,
            },
            {
                description: 'returns false for AI message with similar but different text',
                message: createAIMessage('I will create a support ticket for you'),
                expected: false,
            },
            {
                description: 'returns false for empty AI message',
                message: createAIMessage(''),
                expected: false,
            },
        ])('$description', ({ message, expected }) => {
            expect(isTicketConfirmationMessage(message)).toBe(expected)
        })
    })
})
