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
    CohortApi,
    CohortsListParams,
    CohortsPersonsRetrieveParams,
    PaginatedCohortListApi,
    PatchedAddPersonsToStaticCohortRequestApi,
    PatchedCohortApi,
    PatchedRemovePersonRequestApi,
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

export type cohortsListResponse200 = {
    data: PaginatedCohortListApi
    status: 200
}

export type cohortsListResponseSuccess = cohortsListResponse200 & {
    headers: Headers
}
export type cohortsListResponse = cohortsListResponseSuccess

export const getCohortsListUrl = (projectId: string, params?: CohortsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/cohorts/?${stringifiedParams}`
        : `/api/projects/${projectId}/cohorts/`
}

export const cohortsList = async (
    projectId: string,
    params?: CohortsListParams,
    options?: RequestInit
): Promise<cohortsListResponse> => {
    return apiMutator<cohortsListResponse>(getCohortsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type cohortsCreateResponse201 = {
    data: CohortApi
    status: 201
}

export type cohortsCreateResponseSuccess = cohortsCreateResponse201 & {
    headers: Headers
}
export type cohortsCreateResponse = cohortsCreateResponseSuccess

export const getCohortsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/cohorts/`
}

export const cohortsCreate = async (
    projectId: string,
    cohortApi: NonReadonly<CohortApi>,
    options?: RequestInit
): Promise<cohortsCreateResponse> => {
    return apiMutator<cohortsCreateResponse>(getCohortsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(cohortApi),
    })
}

export type cohortsRetrieveResponse200 = {
    data: CohortApi
    status: 200
}

export type cohortsRetrieveResponseSuccess = cohortsRetrieveResponse200 & {
    headers: Headers
}
export type cohortsRetrieveResponse = cohortsRetrieveResponseSuccess

export const getCohortsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/`
}

export const cohortsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<cohortsRetrieveResponse> => {
    return apiMutator<cohortsRetrieveResponse>(getCohortsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type cohortsUpdateResponse200 = {
    data: CohortApi
    status: 200
}

export type cohortsUpdateResponseSuccess = cohortsUpdateResponse200 & {
    headers: Headers
}
export type cohortsUpdateResponse = cohortsUpdateResponseSuccess

export const getCohortsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/`
}

export const cohortsUpdate = async (
    projectId: string,
    id: number,
    cohortApi: NonReadonly<CohortApi>,
    options?: RequestInit
): Promise<cohortsUpdateResponse> => {
    return apiMutator<cohortsUpdateResponse>(getCohortsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(cohortApi),
    })
}

export type cohortsPartialUpdateResponse200 = {
    data: CohortApi
    status: 200
}

export type cohortsPartialUpdateResponseSuccess = cohortsPartialUpdateResponse200 & {
    headers: Headers
}
export type cohortsPartialUpdateResponse = cohortsPartialUpdateResponseSuccess

export const getCohortsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/`
}

export const cohortsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedCohortApi: NonReadonly<PatchedCohortApi>,
    options?: RequestInit
): Promise<cohortsPartialUpdateResponse> => {
    return apiMutator<cohortsPartialUpdateResponse>(getCohortsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCohortApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type cohortsDestroyResponse405 = {
    data: void
    status: 405
}
export type cohortsDestroyResponseError = cohortsDestroyResponse405 & {
    headers: Headers
}

export type cohortsDestroyResponse = cohortsDestroyResponseError

export const getCohortsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/`
}

export const cohortsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<cohortsDestroyResponse> => {
    return apiMutator<cohortsDestroyResponse>(getCohortsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type cohortsActivityRetrieve2Response200 = {
    data: void
    status: 200
}

export type cohortsActivityRetrieve2ResponseSuccess = cohortsActivityRetrieve2Response200 & {
    headers: Headers
}
export type cohortsActivityRetrieve2Response = cohortsActivityRetrieve2ResponseSuccess

export const getCohortsActivityRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/activity/`
}

export const cohortsActivityRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<cohortsActivityRetrieve2Response> => {
    return apiMutator<cohortsActivityRetrieve2Response>(getCohortsActivityRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type cohortsAddPersonsToStaticCohortPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type cohortsAddPersonsToStaticCohortPartialUpdateResponseSuccess =
    cohortsAddPersonsToStaticCohortPartialUpdateResponse200 & {
        headers: Headers
    }
export type cohortsAddPersonsToStaticCohortPartialUpdateResponse =
    cohortsAddPersonsToStaticCohortPartialUpdateResponseSuccess

export const getCohortsAddPersonsToStaticCohortPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/add_persons_to_static_cohort/`
}

export const cohortsAddPersonsToStaticCohortPartialUpdate = async (
    projectId: string,
    id: number,
    patchedAddPersonsToStaticCohortRequestApi: PatchedAddPersonsToStaticCohortRequestApi,
    options?: RequestInit
): Promise<cohortsAddPersonsToStaticCohortPartialUpdateResponse> => {
    return apiMutator<cohortsAddPersonsToStaticCohortPartialUpdateResponse>(
        getCohortsAddPersonsToStaticCohortPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedAddPersonsToStaticCohortRequestApi),
        }
    )
}

export type cohortsCalculationHistoryRetrieveResponse200 = {
    data: void
    status: 200
}

export type cohortsCalculationHistoryRetrieveResponseSuccess = cohortsCalculationHistoryRetrieveResponse200 & {
    headers: Headers
}
export type cohortsCalculationHistoryRetrieveResponse = cohortsCalculationHistoryRetrieveResponseSuccess

export const getCohortsCalculationHistoryRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/calculation_history/`
}

export const cohortsCalculationHistoryRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<cohortsCalculationHistoryRetrieveResponse> => {
    return apiMutator<cohortsCalculationHistoryRetrieveResponse>(
        getCohortsCalculationHistoryRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type cohortsPersonsRetrieveResponse200 = {
    data: void
    status: 200
}

export type cohortsPersonsRetrieveResponseSuccess = cohortsPersonsRetrieveResponse200 & {
    headers: Headers
}
export type cohortsPersonsRetrieveResponse = cohortsPersonsRetrieveResponseSuccess

export const getCohortsPersonsRetrieveUrl = (projectId: string, id: number, params?: CohortsPersonsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/cohorts/${id}/persons/?${stringifiedParams}`
        : `/api/projects/${projectId}/cohorts/${id}/persons/`
}

export const cohortsPersonsRetrieve = async (
    projectId: string,
    id: number,
    params?: CohortsPersonsRetrieveParams,
    options?: RequestInit
): Promise<cohortsPersonsRetrieveResponse> => {
    return apiMutator<cohortsPersonsRetrieveResponse>(getCohortsPersonsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export type cohortsRemovePersonFromStaticCohortPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type cohortsRemovePersonFromStaticCohortPartialUpdateResponseSuccess =
    cohortsRemovePersonFromStaticCohortPartialUpdateResponse200 & {
        headers: Headers
    }
export type cohortsRemovePersonFromStaticCohortPartialUpdateResponse =
    cohortsRemovePersonFromStaticCohortPartialUpdateResponseSuccess

export const getCohortsRemovePersonFromStaticCohortPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/remove_person_from_static_cohort/`
}

export const cohortsRemovePersonFromStaticCohortPartialUpdate = async (
    projectId: string,
    id: number,
    patchedRemovePersonRequestApi: PatchedRemovePersonRequestApi,
    options?: RequestInit
): Promise<cohortsRemovePersonFromStaticCohortPartialUpdateResponse> => {
    return apiMutator<cohortsRemovePersonFromStaticCohortPartialUpdateResponse>(
        getCohortsRemovePersonFromStaticCohortPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedRemovePersonRequestApi),
        }
    )
}

export type cohortsActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type cohortsActivityRetrieveResponseSuccess = cohortsActivityRetrieveResponse200 & {
    headers: Headers
}
export type cohortsActivityRetrieveResponse = cohortsActivityRetrieveResponseSuccess

export const getCohortsActivityRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/cohorts/activity/`
}

export const cohortsActivityRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<cohortsActivityRetrieveResponse> => {
    return apiMutator<cohortsActivityRetrieveResponse>(getCohortsActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
