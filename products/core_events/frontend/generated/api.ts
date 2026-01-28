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
import type { CoreEventApi, CoreEventsListParams, PaginatedCoreEventListApi, PatchedCoreEventApi } from './api.schemas'

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

/**
 * CRUD operations for Core Events.

Core events are reusable event definitions that can be shared across
Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const getCoreEventsListUrl = (projectId: string, params?: CoreEventsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/core_events/?${stringifiedParams}`
        : `/api/environments/${projectId}/core_events/`
}

export const coreEventsList = async (
    projectId: string,
    params?: CoreEventsListParams,
    options?: RequestInit
): Promise<PaginatedCoreEventListApi> => {
    return apiMutator<PaginatedCoreEventListApi>(getCoreEventsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * CRUD operations for Core Events.

Core events are reusable event definitions that can be shared across
Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const getCoreEventsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/core_events/`
}

export const coreEventsCreate = async (
    projectId: string,
    coreEventApi: NonReadonly<CoreEventApi>,
    options?: RequestInit
): Promise<CoreEventApi> => {
    return apiMutator<CoreEventApi>(getCoreEventsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(coreEventApi),
    })
}

/**
 * CRUD operations for Core Events.

Core events are reusable event definitions that can be shared across
Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const getCoreEventsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/core_events/${id}/`
}

export const coreEventsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CoreEventApi> => {
    return apiMutator<CoreEventApi>(getCoreEventsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * CRUD operations for Core Events.

Core events are reusable event definitions that can be shared across
Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const getCoreEventsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/core_events/${id}/`
}

export const coreEventsUpdate = async (
    projectId: string,
    id: string,
    coreEventApi: NonReadonly<CoreEventApi>,
    options?: RequestInit
): Promise<CoreEventApi> => {
    return apiMutator<CoreEventApi>(getCoreEventsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(coreEventApi),
    })
}

/**
 * CRUD operations for Core Events.

Core events are reusable event definitions that can be shared across
Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const getCoreEventsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/core_events/${id}/`
}

export const coreEventsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCoreEventApi: NonReadonly<PatchedCoreEventApi>,
    options?: RequestInit
): Promise<CoreEventApi> => {
    return apiMutator<CoreEventApi>(getCoreEventsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCoreEventApi),
    })
}

/**
 * CRUD operations for Core Events.

Core events are reusable event definitions that can be shared across
Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const getCoreEventsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/core_events/${id}/`
}

export const coreEventsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getCoreEventsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
