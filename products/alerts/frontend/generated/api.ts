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
import type { AlertApi, AlertsListParams, PaginatedAlertListApi, PatchedAlertApi } from './api.schemas'

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

export const getAlertsListUrl = (projectId: string, params?: AlertsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/alerts/?${stringifiedParams}`
        : `/api/projects/${projectId}/alerts/`
}

export const alertsList = async (
    projectId: string,
    params?: AlertsListParams,
    options?: RequestInit
): Promise<PaginatedAlertListApi> => {
    return apiMutator<PaginatedAlertListApi>(getAlertsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAlertsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/alerts/`
}

export const alertsCreate = async (
    projectId: string,
    alertApi: NonReadonly<AlertApi>,
    options?: RequestInit
): Promise<AlertApi> => {
    return apiMutator<AlertApi>(getAlertsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(alertApi),
    })
}

export const getAlertsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/alerts/${id}/`
}

export const alertsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<AlertApi> => {
    return apiMutator<AlertApi>(getAlertsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAlertsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/alerts/${id}/`
}

export const alertsUpdate = async (
    projectId: string,
    id: string,
    alertApi: NonReadonly<AlertApi>,
    options?: RequestInit
): Promise<AlertApi> => {
    return apiMutator<AlertApi>(getAlertsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(alertApi),
    })
}

export const getAlertsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/alerts/${id}/`
}

export const alertsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedAlertApi: NonReadonly<PatchedAlertApi>,
    options?: RequestInit
): Promise<AlertApi> => {
    return apiMutator<AlertApi>(getAlertsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAlertApi),
    })
}

export const getAlertsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/alerts/${id}/`
}

export const alertsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getAlertsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
