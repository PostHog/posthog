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
    DashboardApi,
    DashboardCollaboratorApi,
    DashboardsCreate2Params,
    DashboardsCreateFromTemplateJsonCreate2Params,
    DashboardsCreateFromTemplateJsonCreateParams,
    DashboardsCreateParams,
    DashboardsCreateUnlistedDashboardCreate2Params,
    DashboardsCreateUnlistedDashboardCreateParams,
    DashboardsDestroy2Params,
    DashboardsDestroyParams,
    DashboardsList2Params,
    DashboardsListParams,
    DashboardsMoveTilePartialUpdate2Params,
    DashboardsMoveTilePartialUpdateParams,
    DashboardsPartialUpdate2Params,
    DashboardsPartialUpdateParams,
    DashboardsRetrieve2Params,
    DashboardsRetrieveParams,
    DashboardsStreamTilesRetrieve2Params,
    DashboardsStreamTilesRetrieveParams,
    DashboardsUpdate2Params,
    DashboardsUpdateParams,
    DataColorThemeApi,
    DataColorThemesList2Params,
    DataColorThemesListParams,
    PaginatedDashboardBasicListApi,
    PaginatedDataColorThemeListApi,
    PatchedDashboardApi,
    PatchedDataColorThemeApi,
    SharingConfigurationApi,
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

export type dashboardsListResponse200 = {
    data: PaginatedDashboardBasicListApi
    status: 200
}

export type dashboardsListResponseSuccess = dashboardsListResponse200 & {
    headers: Headers
}
export type dashboardsListResponse = dashboardsListResponseSuccess

export const getDashboardsListUrl = (projectId: string, params?: DashboardsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/dashboards/?${stringifiedParams}`
        : `/api/environments/${projectId}/dashboards/`
}

export const dashboardsList = async (
    projectId: string,
    params?: DashboardsListParams,
    options?: RequestInit
): Promise<dashboardsListResponse> => {
    return apiMutator<dashboardsListResponse>(getDashboardsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type dashboardsCreateResponse201 = {
    data: DashboardApi
    status: 201
}

export type dashboardsCreateResponseSuccess = dashboardsCreateResponse201 & {
    headers: Headers
}
export type dashboardsCreateResponse = dashboardsCreateResponseSuccess

export const getDashboardsCreateUrl = (projectId: string, params?: DashboardsCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/dashboards/?${stringifiedParams}`
        : `/api/environments/${projectId}/dashboards/`
}

export const dashboardsCreate = async (
    projectId: string,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: DashboardsCreateParams,
    options?: RequestInit
): Promise<dashboardsCreateResponse> => {
    return apiMutator<dashboardsCreateResponse>(getDashboardsCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export type dashboardsCollaboratorsListResponse200 = {
    data: DashboardCollaboratorApi[]
    status: 200
}

export type dashboardsCollaboratorsListResponseSuccess = dashboardsCollaboratorsListResponse200 & {
    headers: Headers
}
export type dashboardsCollaboratorsListResponse = dashboardsCollaboratorsListResponseSuccess

export const getDashboardsCollaboratorsListUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const dashboardsCollaboratorsList = async (
    projectId: string,
    dashboardId: number,
    options?: RequestInit
): Promise<dashboardsCollaboratorsListResponse> => {
    return apiMutator<dashboardsCollaboratorsListResponse>(getDashboardsCollaboratorsListUrl(projectId, dashboardId), {
        ...options,
        method: 'GET',
    })
}

export type dashboardsCollaboratorsCreateResponse201 = {
    data: DashboardCollaboratorApi
    status: 201
}

export type dashboardsCollaboratorsCreateResponseSuccess = dashboardsCollaboratorsCreateResponse201 & {
    headers: Headers
}
export type dashboardsCollaboratorsCreateResponse = dashboardsCollaboratorsCreateResponseSuccess

export const getDashboardsCollaboratorsCreateUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const dashboardsCollaboratorsCreate = async (
    projectId: string,
    dashboardId: number,
    dashboardCollaboratorApi: NonReadonly<DashboardCollaboratorApi>,
    options?: RequestInit
): Promise<dashboardsCollaboratorsCreateResponse> => {
    return apiMutator<dashboardsCollaboratorsCreateResponse>(
        getDashboardsCollaboratorsCreateUrl(projectId, dashboardId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dashboardCollaboratorApi),
        }
    )
}

export type dashboardsCollaboratorsDestroyResponse204 = {
    data: void
    status: 204
}

export type dashboardsCollaboratorsDestroyResponseSuccess = dashboardsCollaboratorsDestroyResponse204 & {
    headers: Headers
}
export type dashboardsCollaboratorsDestroyResponse = dashboardsCollaboratorsDestroyResponseSuccess

export const getDashboardsCollaboratorsDestroyUrl = (projectId: string, dashboardId: number, userUuid: string) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/collaborators/${userUuid}/`
}

export const dashboardsCollaboratorsDestroy = async (
    projectId: string,
    dashboardId: number,
    userUuid: string,
    options?: RequestInit
): Promise<dashboardsCollaboratorsDestroyResponse> => {
    return apiMutator<dashboardsCollaboratorsDestroyResponse>(
        getDashboardsCollaboratorsDestroyUrl(projectId, dashboardId, userUuid),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type dashboardsSharingListResponse200 = {
    data: SharingConfigurationApi[]
    status: 200
}

export type dashboardsSharingListResponseSuccess = dashboardsSharingListResponse200 & {
    headers: Headers
}
export type dashboardsSharingListResponse = dashboardsSharingListResponseSuccess

export const getDashboardsSharingListUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/`
}

export const dashboardsSharingList = async (
    projectId: string,
    dashboardId: number,
    options?: RequestInit
): Promise<dashboardsSharingListResponse> => {
    return apiMutator<dashboardsSharingListResponse>(getDashboardsSharingListUrl(projectId, dashboardId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new password for the sharing configuration.
 */
export type dashboardsSharingPasswordsCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type dashboardsSharingPasswordsCreateResponseSuccess = dashboardsSharingPasswordsCreateResponse200 & {
    headers: Headers
}
export type dashboardsSharingPasswordsCreateResponse = dashboardsSharingPasswordsCreateResponseSuccess

export const getDashboardsSharingPasswordsCreateUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/passwords/`
}

export const dashboardsSharingPasswordsCreate = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<dashboardsSharingPasswordsCreateResponse> => {
    return apiMutator<dashboardsSharingPasswordsCreateResponse>(
        getDashboardsSharingPasswordsCreateUrl(projectId, dashboardId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sharingConfigurationApi),
        }
    )
}

/**
 * Delete a password from the sharing configuration.
 */
export type dashboardsSharingPasswordsDestroyResponse204 = {
    data: void
    status: 204
}

export type dashboardsSharingPasswordsDestroyResponseSuccess = dashboardsSharingPasswordsDestroyResponse204 & {
    headers: Headers
}
export type dashboardsSharingPasswordsDestroyResponse = dashboardsSharingPasswordsDestroyResponseSuccess

export const getDashboardsSharingPasswordsDestroyUrl = (projectId: string, dashboardId: number, passwordId: string) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/passwords/${passwordId}/`
}

export const dashboardsSharingPasswordsDestroy = async (
    projectId: string,
    dashboardId: number,
    passwordId: string,
    options?: RequestInit
): Promise<dashboardsSharingPasswordsDestroyResponse> => {
    return apiMutator<dashboardsSharingPasswordsDestroyResponse>(
        getDashboardsSharingPasswordsDestroyUrl(projectId, dashboardId, passwordId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type dashboardsSharingRefreshCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type dashboardsSharingRefreshCreateResponseSuccess = dashboardsSharingRefreshCreateResponse200 & {
    headers: Headers
}
export type dashboardsSharingRefreshCreateResponse = dashboardsSharingRefreshCreateResponseSuccess

export const getDashboardsSharingRefreshCreateUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/refresh/`
}

export const dashboardsSharingRefreshCreate = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<dashboardsSharingRefreshCreateResponse> => {
    return apiMutator<dashboardsSharingRefreshCreateResponse>(
        getDashboardsSharingRefreshCreateUrl(projectId, dashboardId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sharingConfigurationApi),
        }
    )
}

export type dashboardsRetrieveResponse200 = {
    data: DashboardApi
    status: 200
}

export type dashboardsRetrieveResponseSuccess = dashboardsRetrieveResponse200 & {
    headers: Headers
}
export type dashboardsRetrieveResponse = dashboardsRetrieveResponseSuccess

export const getDashboardsRetrieveUrl = (projectId: string, id: number, params?: DashboardsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/environments/${projectId}/dashboards/${id}/`
}

export const dashboardsRetrieve = async (
    projectId: string,
    id: number,
    params?: DashboardsRetrieveParams,
    options?: RequestInit
): Promise<dashboardsRetrieveResponse> => {
    return apiMutator<dashboardsRetrieveResponse>(getDashboardsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export type dashboardsUpdateResponse200 = {
    data: DashboardApi
    status: 200
}

export type dashboardsUpdateResponseSuccess = dashboardsUpdateResponse200 & {
    headers: Headers
}
export type dashboardsUpdateResponse = dashboardsUpdateResponseSuccess

export const getDashboardsUpdateUrl = (projectId: string, id: number, params?: DashboardsUpdateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/environments/${projectId}/dashboards/${id}/`
}

export const dashboardsUpdate = async (
    projectId: string,
    id: number,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: DashboardsUpdateParams,
    options?: RequestInit
): Promise<dashboardsUpdateResponse> => {
    return apiMutator<dashboardsUpdateResponse>(getDashboardsUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export type dashboardsPartialUpdateResponse200 = {
    data: DashboardApi
    status: 200
}

export type dashboardsPartialUpdateResponseSuccess = dashboardsPartialUpdateResponse200 & {
    headers: Headers
}
export type dashboardsPartialUpdateResponse = dashboardsPartialUpdateResponseSuccess

export const getDashboardsPartialUpdateUrl = (
    projectId: string,
    id: number,
    params?: DashboardsPartialUpdateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/environments/${projectId}/dashboards/${id}/`
}

export const dashboardsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedDashboardApi: NonReadonly<PatchedDashboardApi>,
    params?: DashboardsPartialUpdateParams,
    options?: RequestInit
): Promise<dashboardsPartialUpdateResponse> => {
    return apiMutator<dashboardsPartialUpdateResponse>(getDashboardsPartialUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDashboardApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type dashboardsDestroyResponse405 = {
    data: void
    status: 405
}
export type dashboardsDestroyResponseError = dashboardsDestroyResponse405 & {
    headers: Headers
}

export type dashboardsDestroyResponse = dashboardsDestroyResponseError

export const getDashboardsDestroyUrl = (projectId: string, id: number, params?: DashboardsDestroyParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/environments/${projectId}/dashboards/${id}/`
}

export const dashboardsDestroy = async (
    projectId: string,
    id: number,
    params?: DashboardsDestroyParams,
    options?: RequestInit
): Promise<dashboardsDestroyResponse> => {
    return apiMutator<dashboardsDestroyResponse>(getDashboardsDestroyUrl(projectId, id, params), {
        ...options,
        method: 'DELETE',
    })
}

export type dashboardsMoveTilePartialUpdateResponse200 = {
    data: void
    status: 200
}

export type dashboardsMoveTilePartialUpdateResponseSuccess = dashboardsMoveTilePartialUpdateResponse200 & {
    headers: Headers
}
export type dashboardsMoveTilePartialUpdateResponse = dashboardsMoveTilePartialUpdateResponseSuccess

export const getDashboardsMoveTilePartialUpdateUrl = (
    projectId: string,
    id: number,
    params?: DashboardsMoveTilePartialUpdateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/dashboards/${id}/move_tile/?${stringifiedParams}`
        : `/api/environments/${projectId}/dashboards/${id}/move_tile/`
}

export const dashboardsMoveTilePartialUpdate = async (
    projectId: string,
    id: number,
    patchedDashboardApi: NonReadonly<PatchedDashboardApi>,
    params?: DashboardsMoveTilePartialUpdateParams,
    options?: RequestInit
): Promise<dashboardsMoveTilePartialUpdateResponse> => {
    return apiMutator<dashboardsMoveTilePartialUpdateResponse>(
        getDashboardsMoveTilePartialUpdateUrl(projectId, id, params),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDashboardApi),
        }
    )
}

/**
 * Stream dashboard metadata and tiles via Server-Sent Events. Sends metadata first, then tiles as they are rendered.
 */
export type dashboardsStreamTilesRetrieveResponse200 = {
    data: void
    status: 200
}

export type dashboardsStreamTilesRetrieveResponseSuccess = dashboardsStreamTilesRetrieveResponse200 & {
    headers: Headers
}
export type dashboardsStreamTilesRetrieveResponse = dashboardsStreamTilesRetrieveResponseSuccess

export const getDashboardsStreamTilesRetrieveUrl = (
    projectId: string,
    id: number,
    params?: DashboardsStreamTilesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/dashboards/${id}/stream_tiles/?${stringifiedParams}`
        : `/api/environments/${projectId}/dashboards/${id}/stream_tiles/`
}

export const dashboardsStreamTilesRetrieve = async (
    projectId: string,
    id: number,
    params?: DashboardsStreamTilesRetrieveParams,
    options?: RequestInit
): Promise<dashboardsStreamTilesRetrieveResponse> => {
    return apiMutator<dashboardsStreamTilesRetrieveResponse>(
        getDashboardsStreamTilesRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type dashboardsCreateFromTemplateJsonCreateResponse200 = {
    data: void
    status: 200
}

export type dashboardsCreateFromTemplateJsonCreateResponseSuccess =
    dashboardsCreateFromTemplateJsonCreateResponse200 & {
        headers: Headers
    }
export type dashboardsCreateFromTemplateJsonCreateResponse = dashboardsCreateFromTemplateJsonCreateResponseSuccess

export const getDashboardsCreateFromTemplateJsonCreateUrl = (
    projectId: string,
    params?: DashboardsCreateFromTemplateJsonCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/dashboards/create_from_template_json/?${stringifiedParams}`
        : `/api/environments/${projectId}/dashboards/create_from_template_json/`
}

export const dashboardsCreateFromTemplateJsonCreate = async (
    projectId: string,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: DashboardsCreateFromTemplateJsonCreateParams,
    options?: RequestInit
): Promise<dashboardsCreateFromTemplateJsonCreateResponse> => {
    return apiMutator<dashboardsCreateFromTemplateJsonCreateResponse>(
        getDashboardsCreateFromTemplateJsonCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dashboardApi),
        }
    )
}

/**
 * Creates an unlisted dashboard from template by tag.
Enforces uniqueness (one per tag per team).
Returns 409 if unlisted dashboard with this tag already exists.
 */
export type dashboardsCreateUnlistedDashboardCreateResponse200 = {
    data: void
    status: 200
}

export type dashboardsCreateUnlistedDashboardCreateResponseSuccess =
    dashboardsCreateUnlistedDashboardCreateResponse200 & {
        headers: Headers
    }
export type dashboardsCreateUnlistedDashboardCreateResponse = dashboardsCreateUnlistedDashboardCreateResponseSuccess

export const getDashboardsCreateUnlistedDashboardCreateUrl = (
    projectId: string,
    params?: DashboardsCreateUnlistedDashboardCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/dashboards/create_unlisted_dashboard/?${stringifiedParams}`
        : `/api/environments/${projectId}/dashboards/create_unlisted_dashboard/`
}

export const dashboardsCreateUnlistedDashboardCreate = async (
    projectId: string,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: DashboardsCreateUnlistedDashboardCreateParams,
    options?: RequestInit
): Promise<dashboardsCreateUnlistedDashboardCreateResponse> => {
    return apiMutator<dashboardsCreateUnlistedDashboardCreateResponse>(
        getDashboardsCreateUnlistedDashboardCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dashboardApi),
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
        ? `/api/environments/${projectId}/data_color_themes/?${stringifiedParams}`
        : `/api/environments/${projectId}/data_color_themes/`
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
    return `/api/environments/${projectId}/data_color_themes/`
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
    return `/api/environments/${projectId}/data_color_themes/${id}/`
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
    return `/api/environments/${projectId}/data_color_themes/${id}/`
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
    return `/api/environments/${projectId}/data_color_themes/${id}/`
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
    return `/api/environments/${projectId}/data_color_themes/${id}/`
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

export type dashboardsList2Response200 = {
    data: PaginatedDashboardBasicListApi
    status: 200
}

export type dashboardsList2ResponseSuccess = dashboardsList2Response200 & {
    headers: Headers
}
export type dashboardsList2Response = dashboardsList2ResponseSuccess

export const getDashboardsList2Url = (projectId: string, params?: DashboardsList2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/`
}

export const dashboardsList2 = async (
    projectId: string,
    params?: DashboardsList2Params,
    options?: RequestInit
): Promise<dashboardsList2Response> => {
    return apiMutator<dashboardsList2Response>(getDashboardsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type dashboardsCreate2Response201 = {
    data: DashboardApi
    status: 201
}

export type dashboardsCreate2ResponseSuccess = dashboardsCreate2Response201 & {
    headers: Headers
}
export type dashboardsCreate2Response = dashboardsCreate2ResponseSuccess

export const getDashboardsCreate2Url = (projectId: string, params?: DashboardsCreate2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/`
}

export const dashboardsCreate2 = async (
    projectId: string,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: DashboardsCreate2Params,
    options?: RequestInit
): Promise<dashboardsCreate2Response> => {
    return apiMutator<dashboardsCreate2Response>(getDashboardsCreate2Url(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export type dashboardsCollaboratorsList2Response200 = {
    data: DashboardCollaboratorApi[]
    status: 200
}

export type dashboardsCollaboratorsList2ResponseSuccess = dashboardsCollaboratorsList2Response200 & {
    headers: Headers
}
export type dashboardsCollaboratorsList2Response = dashboardsCollaboratorsList2ResponseSuccess

export const getDashboardsCollaboratorsList2Url = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const dashboardsCollaboratorsList2 = async (
    projectId: string,
    dashboardId: number,
    options?: RequestInit
): Promise<dashboardsCollaboratorsList2Response> => {
    return apiMutator<dashboardsCollaboratorsList2Response>(
        getDashboardsCollaboratorsList2Url(projectId, dashboardId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type dashboardsCollaboratorsCreate2Response201 = {
    data: DashboardCollaboratorApi
    status: 201
}

export type dashboardsCollaboratorsCreate2ResponseSuccess = dashboardsCollaboratorsCreate2Response201 & {
    headers: Headers
}
export type dashboardsCollaboratorsCreate2Response = dashboardsCollaboratorsCreate2ResponseSuccess

export const getDashboardsCollaboratorsCreate2Url = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const dashboardsCollaboratorsCreate2 = async (
    projectId: string,
    dashboardId: number,
    dashboardCollaboratorApi: NonReadonly<DashboardCollaboratorApi>,
    options?: RequestInit
): Promise<dashboardsCollaboratorsCreate2Response> => {
    return apiMutator<dashboardsCollaboratorsCreate2Response>(
        getDashboardsCollaboratorsCreate2Url(projectId, dashboardId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dashboardCollaboratorApi),
        }
    )
}

export type dashboardsCollaboratorsDestroy2Response204 = {
    data: void
    status: 204
}

export type dashboardsCollaboratorsDestroy2ResponseSuccess = dashboardsCollaboratorsDestroy2Response204 & {
    headers: Headers
}
export type dashboardsCollaboratorsDestroy2Response = dashboardsCollaboratorsDestroy2ResponseSuccess

export const getDashboardsCollaboratorsDestroy2Url = (projectId: string, dashboardId: number, userUuid: string) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/${userUuid}/`
}

export const dashboardsCollaboratorsDestroy2 = async (
    projectId: string,
    dashboardId: number,
    userUuid: string,
    options?: RequestInit
): Promise<dashboardsCollaboratorsDestroy2Response> => {
    return apiMutator<dashboardsCollaboratorsDestroy2Response>(
        getDashboardsCollaboratorsDestroy2Url(projectId, dashboardId, userUuid),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type dashboardsSharingList2Response200 = {
    data: SharingConfigurationApi[]
    status: 200
}

export type dashboardsSharingList2ResponseSuccess = dashboardsSharingList2Response200 & {
    headers: Headers
}
export type dashboardsSharingList2Response = dashboardsSharingList2ResponseSuccess

export const getDashboardsSharingList2Url = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/`
}

export const dashboardsSharingList2 = async (
    projectId: string,
    dashboardId: number,
    options?: RequestInit
): Promise<dashboardsSharingList2Response> => {
    return apiMutator<dashboardsSharingList2Response>(getDashboardsSharingList2Url(projectId, dashboardId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new password for the sharing configuration.
 */
export type dashboardsSharingPasswordsCreate2Response200 = {
    data: SharingConfigurationApi
    status: 200
}

export type dashboardsSharingPasswordsCreate2ResponseSuccess = dashboardsSharingPasswordsCreate2Response200 & {
    headers: Headers
}
export type dashboardsSharingPasswordsCreate2Response = dashboardsSharingPasswordsCreate2ResponseSuccess

export const getDashboardsSharingPasswordsCreate2Url = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/passwords/`
}

export const dashboardsSharingPasswordsCreate2 = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<dashboardsSharingPasswordsCreate2Response> => {
    return apiMutator<dashboardsSharingPasswordsCreate2Response>(
        getDashboardsSharingPasswordsCreate2Url(projectId, dashboardId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sharingConfigurationApi),
        }
    )
}

/**
 * Delete a password from the sharing configuration.
 */
export type dashboardsSharingPasswordsDestroy2Response204 = {
    data: void
    status: 204
}

export type dashboardsSharingPasswordsDestroy2ResponseSuccess = dashboardsSharingPasswordsDestroy2Response204 & {
    headers: Headers
}
export type dashboardsSharingPasswordsDestroy2Response = dashboardsSharingPasswordsDestroy2ResponseSuccess

export const getDashboardsSharingPasswordsDestroy2Url = (
    projectId: string,
    dashboardId: number,
    passwordId: string
) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/passwords/${passwordId}/`
}

export const dashboardsSharingPasswordsDestroy2 = async (
    projectId: string,
    dashboardId: number,
    passwordId: string,
    options?: RequestInit
): Promise<dashboardsSharingPasswordsDestroy2Response> => {
    return apiMutator<dashboardsSharingPasswordsDestroy2Response>(
        getDashboardsSharingPasswordsDestroy2Url(projectId, dashboardId, passwordId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type dashboardsSharingRefreshCreate2Response200 = {
    data: SharingConfigurationApi
    status: 200
}

export type dashboardsSharingRefreshCreate2ResponseSuccess = dashboardsSharingRefreshCreate2Response200 & {
    headers: Headers
}
export type dashboardsSharingRefreshCreate2Response = dashboardsSharingRefreshCreate2ResponseSuccess

export const getDashboardsSharingRefreshCreate2Url = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/refresh/`
}

export const dashboardsSharingRefreshCreate2 = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<dashboardsSharingRefreshCreate2Response> => {
    return apiMutator<dashboardsSharingRefreshCreate2Response>(
        getDashboardsSharingRefreshCreate2Url(projectId, dashboardId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sharingConfigurationApi),
        }
    )
}

export type dashboardsRetrieve2Response200 = {
    data: DashboardApi
    status: 200
}

export type dashboardsRetrieve2ResponseSuccess = dashboardsRetrieve2Response200 & {
    headers: Headers
}
export type dashboardsRetrieve2Response = dashboardsRetrieve2ResponseSuccess

export const getDashboardsRetrieve2Url = (projectId: string, id: number, params?: DashboardsRetrieve2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
}

export const dashboardsRetrieve2 = async (
    projectId: string,
    id: number,
    params?: DashboardsRetrieve2Params,
    options?: RequestInit
): Promise<dashboardsRetrieve2Response> => {
    return apiMutator<dashboardsRetrieve2Response>(getDashboardsRetrieve2Url(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export type dashboardsUpdate2Response200 = {
    data: DashboardApi
    status: 200
}

export type dashboardsUpdate2ResponseSuccess = dashboardsUpdate2Response200 & {
    headers: Headers
}
export type dashboardsUpdate2Response = dashboardsUpdate2ResponseSuccess

export const getDashboardsUpdate2Url = (projectId: string, id: number, params?: DashboardsUpdate2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
}

export const dashboardsUpdate2 = async (
    projectId: string,
    id: number,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: DashboardsUpdate2Params,
    options?: RequestInit
): Promise<dashboardsUpdate2Response> => {
    return apiMutator<dashboardsUpdate2Response>(getDashboardsUpdate2Url(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export type dashboardsPartialUpdate2Response200 = {
    data: DashboardApi
    status: 200
}

export type dashboardsPartialUpdate2ResponseSuccess = dashboardsPartialUpdate2Response200 & {
    headers: Headers
}
export type dashboardsPartialUpdate2Response = dashboardsPartialUpdate2ResponseSuccess

export const getDashboardsPartialUpdate2Url = (
    projectId: string,
    id: number,
    params?: DashboardsPartialUpdate2Params
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
}

export const dashboardsPartialUpdate2 = async (
    projectId: string,
    id: number,
    patchedDashboardApi: NonReadonly<PatchedDashboardApi>,
    params?: DashboardsPartialUpdate2Params,
    options?: RequestInit
): Promise<dashboardsPartialUpdate2Response> => {
    return apiMutator<dashboardsPartialUpdate2Response>(getDashboardsPartialUpdate2Url(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDashboardApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type dashboardsDestroy2Response405 = {
    data: void
    status: 405
}
export type dashboardsDestroy2ResponseError = dashboardsDestroy2Response405 & {
    headers: Headers
}

export type dashboardsDestroy2Response = dashboardsDestroy2ResponseError

export const getDashboardsDestroy2Url = (projectId: string, id: number, params?: DashboardsDestroy2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
}

export const dashboardsDestroy2 = async (
    projectId: string,
    id: number,
    params?: DashboardsDestroy2Params,
    options?: RequestInit
): Promise<dashboardsDestroy2Response> => {
    return apiMutator<dashboardsDestroy2Response>(getDashboardsDestroy2Url(projectId, id, params), {
        ...options,
        method: 'DELETE',
    })
}

export type dashboardsMoveTilePartialUpdate2Response200 = {
    data: void
    status: 200
}

export type dashboardsMoveTilePartialUpdate2ResponseSuccess = dashboardsMoveTilePartialUpdate2Response200 & {
    headers: Headers
}
export type dashboardsMoveTilePartialUpdate2Response = dashboardsMoveTilePartialUpdate2ResponseSuccess

export const getDashboardsMoveTilePartialUpdate2Url = (
    projectId: string,
    id: number,
    params?: DashboardsMoveTilePartialUpdate2Params
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/move_tile/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/move_tile/`
}

export const dashboardsMoveTilePartialUpdate2 = async (
    projectId: string,
    id: number,
    patchedDashboardApi: NonReadonly<PatchedDashboardApi>,
    params?: DashboardsMoveTilePartialUpdate2Params,
    options?: RequestInit
): Promise<dashboardsMoveTilePartialUpdate2Response> => {
    return apiMutator<dashboardsMoveTilePartialUpdate2Response>(
        getDashboardsMoveTilePartialUpdate2Url(projectId, id, params),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDashboardApi),
        }
    )
}

/**
 * Stream dashboard metadata and tiles via Server-Sent Events. Sends metadata first, then tiles as they are rendered.
 */
export type dashboardsStreamTilesRetrieve2Response200 = {
    data: void
    status: 200
}

export type dashboardsStreamTilesRetrieve2ResponseSuccess = dashboardsStreamTilesRetrieve2Response200 & {
    headers: Headers
}
export type dashboardsStreamTilesRetrieve2Response = dashboardsStreamTilesRetrieve2ResponseSuccess

export const getDashboardsStreamTilesRetrieve2Url = (
    projectId: string,
    id: number,
    params?: DashboardsStreamTilesRetrieve2Params
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/${id}/stream_tiles/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/stream_tiles/`
}

export const dashboardsStreamTilesRetrieve2 = async (
    projectId: string,
    id: number,
    params?: DashboardsStreamTilesRetrieve2Params,
    options?: RequestInit
): Promise<dashboardsStreamTilesRetrieve2Response> => {
    return apiMutator<dashboardsStreamTilesRetrieve2Response>(
        getDashboardsStreamTilesRetrieve2Url(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type dashboardsCreateFromTemplateJsonCreate2Response200 = {
    data: void
    status: 200
}

export type dashboardsCreateFromTemplateJsonCreate2ResponseSuccess =
    dashboardsCreateFromTemplateJsonCreate2Response200 & {
        headers: Headers
    }
export type dashboardsCreateFromTemplateJsonCreate2Response = dashboardsCreateFromTemplateJsonCreate2ResponseSuccess

export const getDashboardsCreateFromTemplateJsonCreate2Url = (
    projectId: string,
    params?: DashboardsCreateFromTemplateJsonCreate2Params
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/create_from_template_json/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/create_from_template_json/`
}

export const dashboardsCreateFromTemplateJsonCreate2 = async (
    projectId: string,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: DashboardsCreateFromTemplateJsonCreate2Params,
    options?: RequestInit
): Promise<dashboardsCreateFromTemplateJsonCreate2Response> => {
    return apiMutator<dashboardsCreateFromTemplateJsonCreate2Response>(
        getDashboardsCreateFromTemplateJsonCreate2Url(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dashboardApi),
        }
    )
}

/**
 * Creates an unlisted dashboard from template by tag.
Enforces uniqueness (one per tag per team).
Returns 409 if unlisted dashboard with this tag already exists.
 */
export type dashboardsCreateUnlistedDashboardCreate2Response200 = {
    data: void
    status: 200
}

export type dashboardsCreateUnlistedDashboardCreate2ResponseSuccess =
    dashboardsCreateUnlistedDashboardCreate2Response200 & {
        headers: Headers
    }
export type dashboardsCreateUnlistedDashboardCreate2Response = dashboardsCreateUnlistedDashboardCreate2ResponseSuccess

export const getDashboardsCreateUnlistedDashboardCreate2Url = (
    projectId: string,
    params?: DashboardsCreateUnlistedDashboardCreate2Params
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboards/create_unlisted_dashboard/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/create_unlisted_dashboard/`
}

export const dashboardsCreateUnlistedDashboardCreate2 = async (
    projectId: string,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: DashboardsCreateUnlistedDashboardCreate2Params,
    options?: RequestInit
): Promise<dashboardsCreateUnlistedDashboardCreate2Response> => {
    return apiMutator<dashboardsCreateUnlistedDashboardCreate2Response>(
        getDashboardsCreateUnlistedDashboardCreate2Url(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dashboardApi),
        }
    )
}

export type dataColorThemesList2Response200 = {
    data: PaginatedDataColorThemeListApi
    status: 200
}

export type dataColorThemesList2ResponseSuccess = dataColorThemesList2Response200 & {
    headers: Headers
}
export type dataColorThemesList2Response = dataColorThemesList2ResponseSuccess

export const getDataColorThemesList2Url = (projectId: string, params?: DataColorThemesList2Params) => {
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

export const dataColorThemesList2 = async (
    projectId: string,
    params?: DataColorThemesList2Params,
    options?: RequestInit
): Promise<dataColorThemesList2Response> => {
    return apiMutator<dataColorThemesList2Response>(getDataColorThemesList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type dataColorThemesCreate2Response201 = {
    data: DataColorThemeApi
    status: 201
}

export type dataColorThemesCreate2ResponseSuccess = dataColorThemesCreate2Response201 & {
    headers: Headers
}
export type dataColorThemesCreate2Response = dataColorThemesCreate2ResponseSuccess

export const getDataColorThemesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_color_themes/`
}

export const dataColorThemesCreate2 = async (
    projectId: string,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<dataColorThemesCreate2Response> => {
    return apiMutator<dataColorThemesCreate2Response>(getDataColorThemesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataColorThemeApi),
    })
}

export type dataColorThemesRetrieve2Response200 = {
    data: DataColorThemeApi
    status: 200
}

export type dataColorThemesRetrieve2ResponseSuccess = dataColorThemesRetrieve2Response200 & {
    headers: Headers
}
export type dataColorThemesRetrieve2Response = dataColorThemesRetrieve2ResponseSuccess

export const getDataColorThemesRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<dataColorThemesRetrieve2Response> => {
    return apiMutator<dataColorThemesRetrieve2Response>(getDataColorThemesRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type dataColorThemesUpdate2Response200 = {
    data: DataColorThemeApi
    status: 200
}

export type dataColorThemesUpdate2ResponseSuccess = dataColorThemesUpdate2Response200 & {
    headers: Headers
}
export type dataColorThemesUpdate2Response = dataColorThemesUpdate2ResponseSuccess

export const getDataColorThemesUpdate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesUpdate2 = async (
    projectId: string,
    id: number,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<dataColorThemesUpdate2Response> => {
    return apiMutator<dataColorThemesUpdate2Response>(getDataColorThemesUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataColorThemeApi),
    })
}

export type dataColorThemesPartialUpdate2Response200 = {
    data: DataColorThemeApi
    status: 200
}

export type dataColorThemesPartialUpdate2ResponseSuccess = dataColorThemesPartialUpdate2Response200 & {
    headers: Headers
}
export type dataColorThemesPartialUpdate2Response = dataColorThemesPartialUpdate2ResponseSuccess

export const getDataColorThemesPartialUpdate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesPartialUpdate2 = async (
    projectId: string,
    id: number,
    patchedDataColorThemeApi: NonReadonly<PatchedDataColorThemeApi>,
    options?: RequestInit
): Promise<dataColorThemesPartialUpdate2Response> => {
    return apiMutator<dataColorThemesPartialUpdate2Response>(getDataColorThemesPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataColorThemeApi),
    })
}

export type dataColorThemesDestroy2Response204 = {
    data: void
    status: 204
}

export type dataColorThemesDestroy2ResponseSuccess = dataColorThemesDestroy2Response204 & {
    headers: Headers
}
export type dataColorThemesDestroy2Response = dataColorThemesDestroy2ResponseSuccess

export const getDataColorThemesDestroy2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesDestroy2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<dataColorThemesDestroy2Response> => {
    return apiMutator<dataColorThemesDestroy2Response>(getDataColorThemesDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
