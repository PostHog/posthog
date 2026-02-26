import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import { ReadableStream as NodeReadableStream } from 'stream/web'

import api from 'lib/api'

import { Mocks } from '~/mocks/utils'
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
    user: MOCK_DEFAULT_BASIC_USER,
    type: ConversationType.Assistant,
}

export const MOCK_IN_PROGRESS_CONVERSATION: Conversation = {
    ...MOCK_CONVERSATION,
    status: ConversationStatus.InProgress,
}

function buildReadableStream(chunks: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder()
    let index = 0
    const StreamConstructor = globalThis.ReadableStream ?? NodeReadableStream

    return new StreamConstructor({
        pull(controller) {
            if (index < chunks.length) {
                controller.enqueue(encoder.encode(chunks[index]))
                index += 1
            } else {
                controller.close()
            }
        },
    })
}

export function mockStream(chunks: string[] = [': ping\n\n']): jest.SpyInstance {
    return jest.spyOn(api.conversations, 'stream').mockResolvedValue({
        body: buildReadableStream(chunks),
    } as Response)
}

export function mockStreamWithEvents(events: Array<{ event: string; data: unknown }>): jest.SpyInstance {
    const chunks = events.map((entry) => `event: ${entry.event}\ndata: ${JSON.stringify(entry.data)}\n\n`)
    return mockStream(chunks)
}
