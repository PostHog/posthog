/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type {
    ConversationApi,
    ConversationsListParams,
    ConversationsTicketsListParams,
    MessageApi,
    MessageMinimalApi,
    PaginatedConversationListApi,
    PaginatedTicketListApi,
    PatchedConversationApi,
    PatchedTicketApi,
    TicketApi,
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

export type conversationsListResponse200 = {
    data: PaginatedConversationListApi
    status: 200
}

export type conversationsListResponseSuccess = conversationsListResponse200 & {
    headers: Headers
}
export type conversationsListResponse = conversationsListResponseSuccess

export const getConversationsListUrl = (projectId: string, params?: ConversationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/conversations/?${stringifiedParams}`
        : `/api/environments/${projectId}/conversations/`
}

export const conversationsList = async (
    projectId: string,
    params?: ConversationsListParams,
    options?: RequestInit
): Promise<conversationsListResponse> => {
    return apiMutator<conversationsListResponse>(getConversationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Unified endpoint that handles both conversation creation and streaming.

- If message is provided: Start new conversation processing
- If no message: Stream from existing conversation
 */
export type conversationsCreateResponse201 = {
    data: MessageApi
    status: 201
}

export type conversationsCreateResponseSuccess = conversationsCreateResponse201 & {
    headers: Headers
}
export type conversationsCreateResponse = conversationsCreateResponseSuccess

export const getConversationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/conversations/`
}

export const conversationsCreate = async (
    projectId: string,
    messageApi: MessageApi,
    options?: RequestInit
): Promise<conversationsCreateResponse> => {
    return apiMutator<conversationsCreateResponse>(getConversationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageApi),
    })
}

export type conversationsRetrieveResponse200 = {
    data: ConversationApi
    status: 200
}

export type conversationsRetrieveResponseSuccess = conversationsRetrieveResponse200 & {
    headers: Headers
}
export type conversationsRetrieveResponse = conversationsRetrieveResponseSuccess

export const getConversationsRetrieveUrl = (projectId: string, conversation: string) => {
    return `/api/environments/${projectId}/conversations/${conversation}/`
}

export const conversationsRetrieve = async (
    projectId: string,
    conversation: string,
    options?: RequestInit
): Promise<conversationsRetrieveResponse> => {
    return apiMutator<conversationsRetrieveResponse>(getConversationsRetrieveUrl(projectId, conversation), {
        ...options,
        method: 'GET',
    })
}

/**
 * Appends a message to an existing conversation without triggering AI processing.
This is used for client-side generated messages that need to be persisted
(e.g., support ticket confirmation messages).
 */
export type conversationsAppendMessageCreateResponse200 = {
    data: MessageMinimalApi
    status: 200
}

export type conversationsAppendMessageCreateResponseSuccess = conversationsAppendMessageCreateResponse200 & {
    headers: Headers
}
export type conversationsAppendMessageCreateResponse = conversationsAppendMessageCreateResponseSuccess

export const getConversationsAppendMessageCreateUrl = (projectId: string, conversation: string) => {
    return `/api/environments/${projectId}/conversations/${conversation}/append_message/`
}

export const conversationsAppendMessageCreate = async (
    projectId: string,
    conversation: string,
    messageMinimalApi: MessageMinimalApi,
    options?: RequestInit
): Promise<conversationsAppendMessageCreateResponse> => {
    return apiMutator<conversationsAppendMessageCreateResponse>(
        getConversationsAppendMessageCreateUrl(projectId, conversation),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(messageMinimalApi),
        }
    )
}

export type conversationsCancelPartialUpdateResponse200 = {
    data: ConversationApi
    status: 200
}

export type conversationsCancelPartialUpdateResponseSuccess = conversationsCancelPartialUpdateResponse200 & {
    headers: Headers
}
export type conversationsCancelPartialUpdateResponse = conversationsCancelPartialUpdateResponseSuccess

export const getConversationsCancelPartialUpdateUrl = (projectId: string, conversation: string) => {
    return `/api/environments/${projectId}/conversations/${conversation}/cancel/`
}

export const conversationsCancelPartialUpdate = async (
    projectId: string,
    conversation: string,
    patchedConversationApi: NonReadonly<PatchedConversationApi>,
    options?: RequestInit
): Promise<conversationsCancelPartialUpdateResponse> => {
    return apiMutator<conversationsCancelPartialUpdateResponse>(
        getConversationsCancelPartialUpdateUrl(projectId, conversation),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedConversationApi),
        }
    )
}

export type conversationsTicketsListResponse200 = {
    data: PaginatedTicketListApi
    status: 200
}

export type conversationsTicketsListResponseSuccess = conversationsTicketsListResponse200 & {
    headers: Headers
}
export type conversationsTicketsListResponse = conversationsTicketsListResponseSuccess

export const getConversationsTicketsListUrl = (projectId: string, params?: ConversationsTicketsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/conversations/tickets/?${stringifiedParams}`
        : `/api/projects/${projectId}/conversations/tickets/`
}

export const conversationsTicketsList = async (
    projectId: string,
    params?: ConversationsTicketsListParams,
    options?: RequestInit
): Promise<conversationsTicketsListResponse> => {
    return apiMutator<conversationsTicketsListResponse>(getConversationsTicketsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type conversationsTicketsCreateResponse201 = {
    data: TicketApi
    status: 201
}

export type conversationsTicketsCreateResponseSuccess = conversationsTicketsCreateResponse201 & {
    headers: Headers
}
export type conversationsTicketsCreateResponse = conversationsTicketsCreateResponseSuccess

export const getConversationsTicketsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/tickets/`
}

export const conversationsTicketsCreate = async (
    projectId: string,
    ticketApi: NonReadonly<TicketApi>,
    options?: RequestInit
): Promise<conversationsTicketsCreateResponse> => {
    return apiMutator<conversationsTicketsCreateResponse>(getConversationsTicketsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(ticketApi),
    })
}

/**
 * Get single ticket and mark as read by team.
 */
export type conversationsTicketsRetrieveResponse200 = {
    data: TicketApi
    status: 200
}

export type conversationsTicketsRetrieveResponseSuccess = conversationsTicketsRetrieveResponse200 & {
    headers: Headers
}
export type conversationsTicketsRetrieveResponse = conversationsTicketsRetrieveResponseSuccess

export const getConversationsTicketsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/`
}

export const conversationsTicketsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<conversationsTicketsRetrieveResponse> => {
    return apiMutator<conversationsTicketsRetrieveResponse>(getConversationsTicketsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Handle ticket updates including assignee changes.
 */
export type conversationsTicketsUpdateResponse200 = {
    data: TicketApi
    status: 200
}

export type conversationsTicketsUpdateResponseSuccess = conversationsTicketsUpdateResponse200 & {
    headers: Headers
}
export type conversationsTicketsUpdateResponse = conversationsTicketsUpdateResponseSuccess

export const getConversationsTicketsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/`
}

export const conversationsTicketsUpdate = async (
    projectId: string,
    id: string,
    ticketApi: NonReadonly<TicketApi>,
    options?: RequestInit
): Promise<conversationsTicketsUpdateResponse> => {
    return apiMutator<conversationsTicketsUpdateResponse>(getConversationsTicketsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(ticketApi),
    })
}

export type conversationsTicketsPartialUpdateResponse200 = {
    data: TicketApi
    status: 200
}

export type conversationsTicketsPartialUpdateResponseSuccess = conversationsTicketsPartialUpdateResponse200 & {
    headers: Headers
}
export type conversationsTicketsPartialUpdateResponse = conversationsTicketsPartialUpdateResponseSuccess

export const getConversationsTicketsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/`
}

export const conversationsTicketsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedTicketApi: NonReadonly<PatchedTicketApi>,
    options?: RequestInit
): Promise<conversationsTicketsPartialUpdateResponse> => {
    return apiMutator<conversationsTicketsPartialUpdateResponse>(
        getConversationsTicketsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedTicketApi),
        }
    )
}

export type conversationsTicketsDestroyResponse204 = {
    data: void
    status: 204
}

export type conversationsTicketsDestroyResponseSuccess = conversationsTicketsDestroyResponse204 & {
    headers: Headers
}
export type conversationsTicketsDestroyResponse = conversationsTicketsDestroyResponseSuccess

export const getConversationsTicketsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/`
}

export const conversationsTicketsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<conversationsTicketsDestroyResponse> => {
    return apiMutator<conversationsTicketsDestroyResponse>(getConversationsTicketsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
