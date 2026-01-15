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
    DataColorThemeApi,
    DataColorThemesListParams,
    EnvironmentsDataColorThemesListParams,
    PaginatedDataColorThemeListApi,
    PatchedDataColorThemeApi,
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

export type environmentsDataColorThemesListResponse200 = {
    data: PaginatedDataColorThemeListApi
    status: 200
}

export type environmentsDataColorThemesListResponseSuccess = environmentsDataColorThemesListResponse200 & {
    headers: Headers
}
export type environmentsDataColorThemesListResponse = environmentsDataColorThemesListResponseSuccess

export const getEnvironmentsDataColorThemesListUrl = (
    projectId: string,
    params?: EnvironmentsDataColorThemesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/data_color_themes/?${stringifiedParams}`
        : `/api/environments/${projectId}/data_color_themes/`
}

export const environmentsDataColorThemesList = async (
    projectId: string,
    params?: EnvironmentsDataColorThemesListParams,
    options?: RequestInit
): Promise<environmentsDataColorThemesListResponse> => {
    return apiMutator<environmentsDataColorThemesListResponse>(
        getEnvironmentsDataColorThemesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsDataColorThemesCreateResponse201 = {
    data: DataColorThemeApi
    status: 201
}

export type environmentsDataColorThemesCreateResponseSuccess = environmentsDataColorThemesCreateResponse201 & {
    headers: Headers
}
export type environmentsDataColorThemesCreateResponse = environmentsDataColorThemesCreateResponseSuccess

export const getEnvironmentsDataColorThemesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_color_themes/`
}

export const environmentsDataColorThemesCreate = async (
    projectId: string,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<environmentsDataColorThemesCreateResponse> => {
    return apiMutator<environmentsDataColorThemesCreateResponse>(getEnvironmentsDataColorThemesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataColorThemeApi),
    })
}

export type environmentsDataColorThemesRetrieveResponse200 = {
    data: DataColorThemeApi
    status: 200
}

export type environmentsDataColorThemesRetrieveResponseSuccess = environmentsDataColorThemesRetrieveResponse200 & {
    headers: Headers
}
export type environmentsDataColorThemesRetrieveResponse = environmentsDataColorThemesRetrieveResponseSuccess

export const getEnvironmentsDataColorThemesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/data_color_themes/${id}/`
}

export const environmentsDataColorThemesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsDataColorThemesRetrieveResponse> => {
    return apiMutator<environmentsDataColorThemesRetrieveResponse>(
        getEnvironmentsDataColorThemesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsDataColorThemesUpdateResponse200 = {
    data: DataColorThemeApi
    status: 200
}

export type environmentsDataColorThemesUpdateResponseSuccess = environmentsDataColorThemesUpdateResponse200 & {
    headers: Headers
}
export type environmentsDataColorThemesUpdateResponse = environmentsDataColorThemesUpdateResponseSuccess

export const getEnvironmentsDataColorThemesUpdateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/data_color_themes/${id}/`
}

export const environmentsDataColorThemesUpdate = async (
    projectId: string,
    id: number,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<environmentsDataColorThemesUpdateResponse> => {
    return apiMutator<environmentsDataColorThemesUpdateResponse>(
        getEnvironmentsDataColorThemesUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dataColorThemeApi),
        }
    )
}

export type environmentsDataColorThemesPartialUpdateResponse200 = {
    data: DataColorThemeApi
    status: 200
}

export type environmentsDataColorThemesPartialUpdateResponseSuccess =
    environmentsDataColorThemesPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsDataColorThemesPartialUpdateResponse = environmentsDataColorThemesPartialUpdateResponseSuccess

export const getEnvironmentsDataColorThemesPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/data_color_themes/${id}/`
}

export const environmentsDataColorThemesPartialUpdate = async (
    projectId: string,
    id: number,
    patchedDataColorThemeApi: NonReadonly<PatchedDataColorThemeApi>,
    options?: RequestInit
): Promise<environmentsDataColorThemesPartialUpdateResponse> => {
    return apiMutator<environmentsDataColorThemesPartialUpdateResponse>(
        getEnvironmentsDataColorThemesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDataColorThemeApi),
        }
    )
}

export type environmentsDataColorThemesDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsDataColorThemesDestroyResponseSuccess = environmentsDataColorThemesDestroyResponse204 & {
    headers: Headers
}
export type environmentsDataColorThemesDestroyResponse = environmentsDataColorThemesDestroyResponseSuccess

export const getEnvironmentsDataColorThemesDestroyUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/data_color_themes/${id}/`
}

export const environmentsDataColorThemesDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsDataColorThemesDestroyResponse> => {
    return apiMutator<environmentsDataColorThemesDestroyResponse>(
        getEnvironmentsDataColorThemesDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type dataColorThemesListResponse200 = {
    data: PaginatedDataColorThemeListApi
    status: 200
}

export type dataColorThemesListResponseSuccess = dataColorThemesListResponse200 & {
    headers: Headers
}
export type dataColorThemesListResponse = dataColorThemesListResponseSuccess

export const getDataColorThemesListUrl = (projectId: string, params?: DataColorThemesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/data_color_themes/?${stringifiedParams}`
        : `/api/projects/${projectId}/data_color_themes/`
}

export const dataColorThemesList = async (
    projectId: string,
    params?: DataColorThemesListParams,
    options?: RequestInit
): Promise<dataColorThemesListResponse> => {
    return apiMutator<dataColorThemesListResponse>(getDataColorThemesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type dataColorThemesCreateResponse201 = {
    data: DataColorThemeApi
    status: 201
}

export type dataColorThemesCreateResponseSuccess = dataColorThemesCreateResponse201 & {
    headers: Headers
}
export type dataColorThemesCreateResponse = dataColorThemesCreateResponseSuccess

export const getDataColorThemesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/data_color_themes/`
}

export const dataColorThemesCreate = async (
    projectId: string,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<dataColorThemesCreateResponse> => {
    return apiMutator<dataColorThemesCreateResponse>(getDataColorThemesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataColorThemeApi),
    })
}

export type dataColorThemesRetrieveResponse200 = {
    data: DataColorThemeApi
    status: 200
}

export type dataColorThemesRetrieveResponseSuccess = dataColorThemesRetrieveResponse200 & {
    headers: Headers
}
export type dataColorThemesRetrieveResponse = dataColorThemesRetrieveResponseSuccess

export const getDataColorThemesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<dataColorThemesRetrieveResponse> => {
    return apiMutator<dataColorThemesRetrieveResponse>(getDataColorThemesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type dataColorThemesUpdateResponse200 = {
    data: DataColorThemeApi
    status: 200
}

export type dataColorThemesUpdateResponseSuccess = dataColorThemesUpdateResponse200 & {
    headers: Headers
}
export type dataColorThemesUpdateResponse = dataColorThemesUpdateResponseSuccess

export const getDataColorThemesUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesUpdate = async (
    projectId: string,
    id: number,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<dataColorThemesUpdateResponse> => {
    return apiMutator<dataColorThemesUpdateResponse>(getDataColorThemesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataColorThemeApi),
    })
}

export type dataColorThemesPartialUpdateResponse200 = {
    data: DataColorThemeApi
    status: 200
}

export type dataColorThemesPartialUpdateResponseSuccess = dataColorThemesPartialUpdateResponse200 & {
    headers: Headers
}
export type dataColorThemesPartialUpdateResponse = dataColorThemesPartialUpdateResponseSuccess

export const getDataColorThemesPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesPartialUpdate = async (
    projectId: string,
    id: number,
    patchedDataColorThemeApi: NonReadonly<PatchedDataColorThemeApi>,
    options?: RequestInit
): Promise<dataColorThemesPartialUpdateResponse> => {
    return apiMutator<dataColorThemesPartialUpdateResponse>(getDataColorThemesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataColorThemeApi),
    })
}

export type dataColorThemesDestroyResponse204 = {
    data: void
    status: 204
}

export type dataColorThemesDestroyResponseSuccess = dataColorThemesDestroyResponse204 & {
    headers: Headers
}
export type dataColorThemesDestroyResponse = dataColorThemesDestroyResponseSuccess

export const getDataColorThemesDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<dataColorThemesDestroyResponse> => {
    return apiMutator<dataColorThemesDestroyResponse>(getDataColorThemesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
