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
): Promise<PaginatedCohortListApi> => {
    return apiMutator<PaginatedCohortListApi>(getCohortsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCohortsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/cohorts/`
}

export const cohortsCreate = async (
    projectId: string,
    cohortApi: NonReadonly<CohortApi>,
    options?: RequestInit
): Promise<CohortApi> => {
    return apiMutator<CohortApi>(getCohortsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(cohortApi),
    })
}

export const getCohortsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/`
}

export const cohortsRetrieve = async (projectId: string, id: number, options?: RequestInit): Promise<CohortApi> => {
    return apiMutator<CohortApi>(getCohortsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCohortsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/`
}

export const cohortsUpdate = async (
    projectId: string,
    id: number,
    cohortApi: NonReadonly<CohortApi>,
    options?: RequestInit
): Promise<CohortApi> => {
    return apiMutator<CohortApi>(getCohortsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(cohortApi),
    })
}

export const getCohortsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/`
}

export const cohortsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedCohortApi: NonReadonly<PatchedCohortApi>,
    options?: RequestInit
): Promise<CohortApi> => {
    return apiMutator<CohortApi>(getCohortsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCohortApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getCohortsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/`
}

export const cohortsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getCohortsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCohortsActivityRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/activity/`
}

export const cohortsActivityRetrieve2 = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getCohortsActivityRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCohortsAddPersonsToStaticCohortPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/add_persons_to_static_cohort/`
}

export const cohortsAddPersonsToStaticCohortPartialUpdate = async (
    projectId: string,
    id: number,
    patchedAddPersonsToStaticCohortRequestApi: PatchedAddPersonsToStaticCohortRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCohortsAddPersonsToStaticCohortPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAddPersonsToStaticCohortRequestApi),
    })
}

export const getCohortsCalculationHistoryRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/calculation_history/`
}

export const cohortsCalculationHistoryRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCohortsCalculationHistoryRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<void> => {
    return apiMutator<void>(getCohortsPersonsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getCohortsRemovePersonFromStaticCohortPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/cohorts/${id}/remove_person_from_static_cohort/`
}

export const cohortsRemovePersonFromStaticCohortPartialUpdate = async (
    projectId: string,
    id: number,
    patchedRemovePersonRequestApi: PatchedRemovePersonRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCohortsRemovePersonFromStaticCohortPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedRemovePersonRequestApi),
    })
}

export const getCohortsActivityRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/cohorts/activity/`
}

export const cohortsActivityRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getCohortsActivityRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
