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
    BulkUpdateTagsRequestApi,
    BulkUpdateTagsResponseApi,
    ConversationsTicketsListParams,
    ConversationsViewsListParams,
    PaginatedTicketListApi,
    PaginatedTicketViewListApi,
    PatchedTicketApi,
    SuggestReplyResponseApi,
    TicketApi,
    TicketViewApi,
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

export const getConversationsViewsListUrl = (projectId: string, params?: ConversationsViewsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/conversations/views/?${stringifiedParams}`
        : `/api/environments/${projectId}/conversations/views/`
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
    return `/api/environments/${projectId}/conversations/views/`
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
    return `/api/environments/${projectId}/conversations/views/${shortId}/`
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
    return `/api/environments/${projectId}/conversations/views/${shortId}/`
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

/**
 * List tickets with person data attached.
 */
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
    ticketApi: NonReadonly<TicketApi>,
    options?: RequestInit
): Promise<TicketApi> => {
    return apiMutator<TicketApi>(getConversationsTicketsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(ticketApi),
    })
}

/**
 * Get single ticket and mark as read by team.
 */
export const getConversationsTicketsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/`
}

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

/**
 * Handle ticket updates including assignee changes.
 */
export const getConversationsTicketsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/`
}

export const conversationsTicketsUpdate = async (
    projectId: string,
    id: string,
    ticketApi: NonReadonly<TicketApi>,
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
    patchedTicketApi: NonReadonly<PatchedTicketApi>,
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

export const getConversationsTicketsSuggestReplyCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/conversations/tickets/${id}/suggest_reply/`
}

export const conversationsTicketsSuggestReplyCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SuggestReplyResponseApi> => {
    return apiMutator<SuggestReplyResponseApi>(getConversationsTicketsSuggestReplyCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

/**
 * Bulk update tags on multiple objects.

Accepts:
- {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}

Actions:
- "add": Add tags to existing tags on each object
- "remove": Remove specific tags from each object
- "set": Replace all tags on each object with the provided list
 */
export const getConversationsTicketsBulkUpdateTagsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/tickets/bulk_update_tags/`
}

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

/**
 * Get total unread ticket count for the team.

Returns the sum of unread_team_count for all non-resolved tickets.
Cached in Redis for 30 seconds, invalidated on changes.
 */
export const getConversationsTicketsUnreadCountRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/conversations/tickets/unread_count/`
}

export const conversationsTicketsUnreadCountRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<TicketApi> => {
    return apiMutator<TicketApi>(getConversationsTicketsUnreadCountRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
