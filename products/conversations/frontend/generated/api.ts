import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    AiFeedbackRequestApi,
    BulkUpdateStatusRequestApi,
    BulkUpdateStatusResponseApi,
    BulkUpdateTagsRequestApi,
    BulkUpdateTagsResponseApi,
    ComposeTicketApi,
    ComposeTicketResponseApi,
    ConversationApi,
    ConversationsListParams,
    ConversationsTicketsListParams,
    ConversationsTicketsMessagesListParams,
    ConversationsViewsListParams,
    MessageApi,
    MessageMinimalApi,
    PaginatedConversationMinimalListApi,
    PaginatedTicketListApi,
    PaginatedTicketMessageListApi,
    PaginatedTicketViewListApi,
    PatchedConversationApi,
    PatchedTicketApi,
    SandboxMessageResponseApi,
    SandboxOpenApi,
    TicketApi,
    TicketMessageApi,
    TicketReplyRequestApi,
    TicketViewApi,
    ZendeskImportJobApi,
    ZendeskImportStartApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getConversationsListUrl = (projectId: string, params?: ConversationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/conversations/?${stringifiedParams}`
        : `/api/projects/${projectId}/conversations/`
}

export const conversationsList = async (
    projectId: string,
    params?: ConversationsListParams,
    options?: RequestInit
): Promise<PaginatedConversationMinimalListApi> => {
    return apiMutator<PaginatedConversationMinimalListApi>(getConversationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/`
}

/**
 * Unified endpoint that handles both conversation creation and streaming.
 *
 * - If message is provided: Start new conversation processing
 * - If no message: Stream from existing conversation
 */
export const conversationsCreate = async (
    projectId: string,
    messageApi: MessageApi,
    options?: RequestInit
): Promise<MessageApi> => {
    return apiMutator<MessageApi>(getConversationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageApi),
    })
}

export const getConversationsRetrieveUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/`
}

export const conversationsRetrieve = async (
    projectId: string,
    conversation: string,
    options?: RequestInit
): Promise<ConversationApi> => {
    return apiMutator<ConversationApi>(getConversationsRetrieveUrl(projectId, conversation), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsDestroyUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/`
}

/**
 * Delete a conversation.
 */
export const conversationsDestroy = async (
    projectId: string,
    conversation: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getConversationsDestroyUrl(projectId, conversation), {
        ...options,
        method: 'DELETE',
    })
}

export const getConversationsAppendMessageCreateUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/append_message/`
}

/**
 * Appends a message to an existing conversation without triggering AI processing.
 * This is used for client-side generated messages that need to be persisted
 * (e.g., support ticket confirmation messages).
 */
export const conversationsAppendMessageCreate = async (
    projectId: string,
    conversation: string,
    messageMinimalApi: MessageMinimalApi,
    options?: RequestInit
): Promise<MessageMinimalApi> => {
    return apiMutator<MessageMinimalApi>(getConversationsAppendMessageCreateUrl(projectId, conversation), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageMinimalApi),
    })
}

export const getConversationsCancelPartialUpdateUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/cancel/`
}

/**
 * Cancel the conversation's in-progress LangGraph run.
 */
export const conversationsCancelPartialUpdate = async (
    projectId: string,
    conversation: string,
    patchedConversationApi?: NonReadonly<PatchedConversationApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getConversationsCancelPartialUpdateUrl(projectId, conversation), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedConversationApi),
    })
}

export const getConversationsOpenCreateUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/open/`
}

/**
 * Create-or-resume a sandbox conversation — the single sandbox session opener. With `content`, processes the turn (first message, in-progress follow-up, or terminal resume); without `content`, warms a sandbox that idles awaiting the first message. Returns the `(task, run)` handle the frontend opens SSE against. The conversation row is created on first use from the URL id.
 */
export const conversationsOpenCreate = async (
    projectId: string,
    conversation: string,
    sandboxOpenApi?: SandboxOpenApi,
    options?: RequestInit
): Promise<SandboxMessageResponseApi | void> => {
    return apiMutator<SandboxMessageResponseApi | void>(getConversationsOpenCreateUrl(projectId, conversation), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sandboxOpenApi),
    })
}

export const getConversationsQueueRetrieveUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/queue/`
}

export const conversationsQueueRetrieve = async (
    projectId: string,
    conversation: string,
    options?: RequestInit
): Promise<ConversationApi> => {
    return apiMutator<ConversationApi>(getConversationsQueueRetrieveUrl(projectId, conversation), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsQueueCreateUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/queue/`
}

export const conversationsQueueCreate = async (
    projectId: string,
    conversation: string,
    conversationApi?: NonReadonly<ConversationApi>,
    options?: RequestInit
): Promise<ConversationApi> => {
    return apiMutator<ConversationApi>(getConversationsQueueCreateUrl(projectId, conversation), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(conversationApi),
    })
}

export const getConversationsQueuePartialUpdateUrl = (projectId: string, conversation: string, queueId: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/queue/${queueId}/`
}

export const conversationsQueuePartialUpdate = async (
    projectId: string,
    conversation: string,
    queueId: string,
    patchedConversationApi?: NonReadonly<PatchedConversationApi>,
    options?: RequestInit
): Promise<ConversationApi> => {
    return apiMutator<ConversationApi>(getConversationsQueuePartialUpdateUrl(projectId, conversation, queueId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedConversationApi),
    })
}

export const getConversationsQueueDestroyUrl = (projectId: string, conversation: string, queueId: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/queue/${queueId}/`
}

export const conversationsQueueDestroy = async (
    projectId: string,
    conversation: string,
    queueId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getConversationsQueueDestroyUrl(projectId, conversation, queueId), {
        ...options,
        method: 'DELETE',
    })
}

export const getConversationsQueueClearCreateUrl = (projectId: string, conversation: string) => {
    return `/api/projects/${projectId}/conversations/${conversation}/queue/clear/`
}

export const conversationsQueueClearCreate = async (
    projectId: string,
    conversation: string,
    conversationApi?: NonReadonly<ConversationApi>,
    options?: RequestInit
): Promise<ConversationApi> => {
    return apiMutator<ConversationApi>(getConversationsQueueClearCreateUrl(projectId, conversation), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(conversationApi),
    })
}

export const getConversationsTicketsListUrl = (projectId: string, params?: ConversationsTicketsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/conversations/tickets/?${stringifiedParams}`
        : `/api/projects/${projectId}/conversations/tickets/`
}

/**
 * List tickets with person data attached.
 */
export const conversationsTicketsList = async (
    projectId: string,
    params?: ConversationsTicketsListParams,
    options?: RequestInit
): Promise<PaginatedTicketListApi> => {
    return apiMutator<PaginatedTicketListApi>(getConversationsTicketsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsTicketsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/tickets/`
}

export const conversationsTicketsCreate = async (
    projectId: string,
    ticketApi?: NonReadonly<TicketApi>,
    options?: RequestInit
): Promise<TicketApi> => {
    return apiMutator<TicketApi>(getConversationsTicketsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(ticketApi),
    })
}

export const getConversationsTicketsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/`
}

/**
 * Get single ticket and mark as read by team.
 */
export const conversationsTicketsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TicketApi> => {
    return apiMutator<TicketApi>(getConversationsTicketsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsTicketsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/`
}

/**
 * Handle ticket updates including assignee changes.
 */
export const conversationsTicketsUpdate = async (
    projectId: string,
    id: string,
    ticketApi?: NonReadonly<TicketApi>,
    options?: RequestInit
): Promise<TicketApi> => {
    return apiMutator<TicketApi>(getConversationsTicketsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(ticketApi),
    })
}

export const getConversationsTicketsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/`
}

export const conversationsTicketsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedTicketApi?: NonReadonly<PatchedTicketApi>,
    options?: RequestInit
): Promise<TicketApi> => {
    return apiMutator<TicketApi>(getConversationsTicketsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTicketApi),
    })
}

export const getConversationsTicketsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/`
}

export const conversationsTicketsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getConversationsTicketsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getConversationsTicketsAiFeedbackCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/ai_feedback/`
}

/**
 * Record reviewer feedback on an AI reply, captured to the internal analytics project.
 */
export const conversationsTicketsAiFeedbackCreate = async (
    projectId: string,
    id: string,
    aiFeedbackRequestApi: AiFeedbackRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getConversationsTicketsAiFeedbackCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(aiFeedbackRequestApi),
    })
}

export const getConversationsTicketsMessagesListUrl = (
    projectId: string,
    id: string,
    params?: ConversationsTicketsMessagesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/conversations/tickets/${id}/messages/?${stringifiedParams}`
        : `/api/projects/${projectId}/conversations/tickets/${id}/messages/`
}

/**
 * Return the message thread for a ticket, ordered chronologically (paginated).
 */
export const conversationsTicketsMessagesList = async (
    projectId: string,
    id: string,
    params?: ConversationsTicketsMessagesListParams,
    options?: RequestInit
): Promise<PaginatedTicketMessageListApi> => {
    return apiMutator<PaginatedTicketMessageListApi>(getConversationsTicketsMessagesListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsTicketsReplyCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/reply/`
}

/**
 * Post a reply or internal note to a ticket.
 *
 * With is_private=false, the reply is delivered to the customer via the
 * ticket's channel (email, Slack, Teams, GitHub). With is_private=true,
 * the message is stored as an internal note only visible to team members.
 */
export const conversationsTicketsReplyCreate = async (
    projectId: string,
    id: string,
    ticketReplyRequestApi: TicketReplyRequestApi,
    options?: RequestInit
): Promise<TicketMessageApi> => {
    return apiMutator<TicketMessageApi>(getConversationsTicketsReplyCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(ticketReplyRequestApi),
    })
}

export const getConversationsTicketsBulkUpdateStatusCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/tickets/bulk_update_status/`
}

/**
 * Update the status of multiple tickets in a single request.
 *
 * Only tickets belonging to the current team are affected; other-team UUIDs
 * are silently ignored.  Tickets already in the requested status are skipped.
 */
export const conversationsTicketsBulkUpdateStatusCreate = async (
    projectId: string,
    bulkUpdateStatusRequestApi: BulkUpdateStatusRequestApi,
    options?: RequestInit
): Promise<BulkUpdateStatusResponseApi> => {
    return apiMutator<BulkUpdateStatusResponseApi>(getConversationsTicketsBulkUpdateStatusCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bulkUpdateStatusRequestApi),
    })
}

export const getConversationsTicketsBulkUpdateTagsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/tickets/bulk_update_tags/`
}

/**
 * Bulk update tags on multiple objects.
 *
 * PAT access: this action has no ``required_scopes=`` on the decorator —
 * inheriting viewsets must add ``"bulk_update_tags"`` to their
 * ``scope_object_write_actions`` list to accept personal API keys.
 * Without that opt-in, ``APIScopePermission`` rejects PAT requests with
 * "This action does not support personal API key access". Done per-viewset
 * so granting ``<scope>:write`` for one resource doesn't leak access to
 * sibling resources that share this mixin.
 *
 * Accepts:
 * - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}
 *
 * Actions:
 * - "add": Add tags to existing tags on each object
 * - "remove": Remove specific tags from each object
 * - "set": Replace all tags on each object with the provided list
 */
export const conversationsTicketsBulkUpdateTagsCreate = async (
    projectId: string,
    bulkUpdateTagsRequestApi: BulkUpdateTagsRequestApi,
    options?: RequestInit
): Promise<BulkUpdateTagsResponseApi> => {
    return apiMutator<BulkUpdateTagsResponseApi>(getConversationsTicketsBulkUpdateTagsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bulkUpdateTagsRequestApi),
    })
}

export const getConversationsTicketsComposeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/tickets/compose/`
}

/**
 * Create a new outbound ticket and send the first message to the customer.
 */
export const conversationsTicketsComposeCreate = async (
    projectId: string,
    composeTicketApi: ComposeTicketApi,
    options?: RequestInit
): Promise<ComposeTicketResponseApi> => {
    return apiMutator<ComposeTicketResponseApi>(getConversationsTicketsComposeCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(composeTicketApi),
    })
}

export const getConversationsTicketsUnreadCountRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/tickets/unread_count/`
}

/**
 * Get total unread ticket count for the team.
 *
 * Returns the sum of unread_team_count for all non-resolved tickets.
 * Cached in Redis for 30 seconds, invalidated on changes.
 */
export const conversationsTicketsUnreadCountRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<TicketApi> => {
    return apiMutator<TicketApi>(getConversationsTicketsUnreadCountRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsViewsListUrl = (projectId: string, params?: ConversationsViewsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/conversations/views/?${stringifiedParams}`
        : `/api/projects/${projectId}/conversations/views/`
}

export const conversationsViewsList = async (
    projectId: string,
    params?: ConversationsViewsListParams,
    options?: RequestInit
): Promise<PaginatedTicketViewListApi> => {
    return apiMutator<PaginatedTicketViewListApi>(getConversationsViewsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsViewsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/views/`
}

export const conversationsViewsCreate = async (
    projectId: string,
    ticketViewApi: NonReadonly<TicketViewApi>,
    options?: RequestInit
): Promise<TicketViewApi> => {
    return apiMutator<TicketViewApi>(getConversationsViewsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(ticketViewApi),
    })
}

export const getConversationsViewsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/conversations/views/${shortId}/`
}

export const conversationsViewsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<TicketViewApi> => {
    return apiMutator<TicketViewApi>(getConversationsViewsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getConversationsViewsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/conversations/views/${shortId}/`
}

export const conversationsViewsDestroy = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getConversationsViewsDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

export const getConversationsZendeskImportsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/zendesk_imports/`
}

export const conversationsZendeskImportsCreate = async (
    projectId: string,
    zendeskImportStartApi: ZendeskImportStartApi,
    options?: RequestInit
): Promise<ZendeskImportJobApi> => {
    return apiMutator<ZendeskImportJobApi>(getConversationsZendeskImportsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(zendeskImportStartApi),
    })
}

export const getConversationsZendeskImportsStatusRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/zendesk_imports/status/`
}

export const conversationsZendeskImportsStatusRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<ZendeskImportJobApi> => {
    return apiMutator<ZendeskImportJobApi>(getConversationsZendeskImportsStatusRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
