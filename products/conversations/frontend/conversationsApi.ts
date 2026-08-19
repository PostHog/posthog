import api, { ApiConfig, ApiMethodOptions, PaginatedResponse } from 'lib/api'

import { Conversation, ConversationDetail, ConversationQueueResponse } from '~/types'

import {
    conversationsAppendMessageCreate,
    conversationsCancelPartialUpdate,
    conversationsList,
    conversationsOpenCreate,
    conversationsQueueClearCreate,
    conversationsQueueCreate,
    conversationsQueueDestroy,
    conversationsQueuePartialUpdate,
    conversationsQueueRetrieve,
    conversationsRetrieve,
    getConversationsCreateUrl,
} from './generated/api'

// nosemgrep: prefer-codegen-api
const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export const conversationsApi = {
    async stream(data: Record<string, any>, options?: ApiMethodOptions): Promise<Response> {
        return api.createResponse(getConversationsCreateUrl(projectId()), data, options)
    },
    async open(
        conversationId: string,
        data: Record<string, any>
    ): Promise<{
        task_id: string
        run_id: string
        trace_id: string | null
        run_status: 'queued' | 'in_progress'
        just_created_run: boolean
    } | null> {
        return (await conversationsOpenCreate(
            projectId(),
            conversationId,
            data as Parameters<typeof conversationsOpenCreate>[2]
        )) as {
            task_id: string
            run_id: string
            trace_id: string | null
            run_status: 'queued' | 'in_progress'
            just_created_run: boolean
        } | null
    },
    async cancel(conversationId: string): Promise<void> {
        await conversationsCancelPartialUpdate(projectId(), conversationId)
    },
    async list(): Promise<PaginatedResponse<Conversation>> {
        return (await conversationsList(projectId())) as unknown as PaginatedResponse<Conversation>
    },
    async get(conversationId: string): Promise<ConversationDetail> {
        return (await conversationsRetrieve(projectId(), conversationId)) as unknown as ConversationDetail
    },
    async appendMessage(conversationId: string, content: string): Promise<{ id: string }> {
        return (await conversationsAppendMessageCreate(projectId(), conversationId, { content })) as unknown as {
            id: string
        }
    },
    queue: {
        async list(conversationId: string): Promise<ConversationQueueResponse> {
            return (await conversationsQueueRetrieve(
                projectId(),
                conversationId
            )) as unknown as ConversationQueueResponse
        },
        async enqueue(conversationId: string, data: Record<string, any>): Promise<ConversationQueueResponse> {
            return (await conversationsQueueCreate(
                projectId(),
                conversationId,
                data as Parameters<typeof conversationsQueueCreate>[2]
            )) as unknown as ConversationQueueResponse
        },
        async update(conversationId: string, queueId: string, content: string): Promise<ConversationQueueResponse> {
            return (await conversationsQueuePartialUpdate(projectId(), conversationId, queueId, {
                content,
            })) as unknown as ConversationQueueResponse
        },
        async delete(conversationId: string, queueId: string): Promise<ConversationQueueResponse> {
            return (await conversationsQueueDestroy(
                projectId(),
                conversationId,
                queueId
            )) as unknown as ConversationQueueResponse
        },
        async clear(conversationId: string): Promise<ConversationQueueResponse> {
            return (await conversationsQueueClearCreate(
                projectId(),
                conversationId,
                {} as Parameters<typeof conversationsQueueClearCreate>[2]
            )) as unknown as ConversationQueueResponse
        },
    },
}
