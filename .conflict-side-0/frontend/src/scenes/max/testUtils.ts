import { ReadableStream } from 'node:stream/web'

import api from 'lib/api'

import { Mocks } from '~/mocks/utils'
import { AssistantEventType, AssistantMessage, AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { Conversation, ConversationStatus, ConversationType } from '~/types'

export const maxMocks: Mocks = {
    get: {
        '/api/environments/:team_id/conversations/': { results: [] },
    },
    post: {
        'api/environments/:team_id/query': { questions: ['Question'] },
        '/api/environments/:team_id/conversations/': {},
    },
}

export const MOCK_CONVERSATION_ID = 'mock-conversation-id'
export const MOCK_TEMP_CONVERSATION_ID = 'temp-temp-conversation-id'

export const MOCK_CONVERSATION: Conversation = {
    id: MOCK_CONVERSATION_ID,
    status: ConversationStatus.Idle,
    title: 'Testing',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    type: ConversationType.Assistant,
}

export const MOCK_IN_PROGRESS_CONVERSATION: Conversation = {
    ...MOCK_CONVERSATION,
    status: ConversationStatus.InProgress,
}

export function mockStream(): jest.SpyInstance {
    return jest.spyOn(api.conversations, 'stream').mockImplementation(async (payload): Promise<Response> => {
        const encoder = new TextEncoder()
        const stream = new ReadableStream({
            async start(controller) {
                function enqueue({ event, data }: { event: AssistantEventType; data: any }): void {
                    controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`))
                }

                const conversation: Conversation = {
                    id: MOCK_CONVERSATION_ID,
                    status: ConversationStatus.InProgress,
                    title: '',
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                    type: ConversationType.Assistant,
                }
                enqueue({
                    event: AssistantEventType.Conversation,
                    data: conversation,
                })

                // Clear queues
                await new Promise((r) => setTimeout(r))

                // Simulate the main assistant response
                const assistantResponseMessage: AssistantMessage = {
                    id: 'mock-assistant-msg-1', // Finalized messages usually have an ID
                    type: AssistantMessageType.Assistant,
                    content: `Response to "${payload?.content}"`, // Use input from payload
                }
                enqueue({
                    event: AssistantEventType.Message,
                    data: assistantResponseMessage,
                })

                // Clear queues
                await new Promise((r) => setTimeout(r))

                // Close the stream
                controller.close()
            },
        })

        const response = {
            body: {
                getReader: () => stream.getReader(),
            },
        }

        return response as any
    })
}
