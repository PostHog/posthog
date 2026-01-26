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
    DashboardsCreateFromTemplateJsonCreateParams,
    DashboardsCreateParams,
    DashboardsCreateUnlistedDashboardCreateParams,
    DashboardsDestroyParams,
    DashboardsListParams,
    DashboardsMoveTilePartialUpdateParams,
    DashboardsPartialUpdateParams,
    DashboardsRetrieveParams,
    DashboardsStreamTilesRetrieveParams,
    DashboardsUpdateParams,
    DataColorThemeApi,
    DataColorThemesListParams,
    EnvironmentsDashboardsCreateFromTemplateJsonCreateParams,
    EnvironmentsDashboardsCreateParams,
    EnvironmentsDashboardsCreateUnlistedDashboardCreateParams,
    EnvironmentsDashboardsDestroyParams,
    EnvironmentsDashboardsListParams,
    EnvironmentsDashboardsMoveTilePartialUpdateParams,
    EnvironmentsDashboardsPartialUpdateParams,
    EnvironmentsDashboardsRetrieveParams,
    EnvironmentsDashboardsStreamTilesRetrieveParams,
    EnvironmentsDashboardsUpdateParams,
    EnvironmentsDataColorThemesListParams,
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

export type environmentsDashboardsListResponse200 = {
    data: PaginatedDashboardBasicListApi
    status: 200
}

export type environmentsDashboardsListResponseSuccess = environmentsDashboardsListResponse200 & {
    headers: Headers
}
export type environmentsDashboardsListResponse = environmentsDashboardsListResponseSuccess

export const getEnvironmentsDashboardsListUrl = (projectId: string, params?: EnvironmentsDashboardsListParams) => {
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

export const environmentsDashboardsList = async (
    projectId: string,
    params?: EnvironmentsDashboardsListParams,
    options?: RequestInit
): Promise<environmentsDashboardsListResponse> => {
    return apiMutator<environmentsDashboardsListResponse>(getEnvironmentsDashboardsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsDashboardsCreateResponse201 = {
    data: DashboardApi
    status: 201
}

export type environmentsDashboardsCreateResponseSuccess = environmentsDashboardsCreateResponse201 & {
    headers: Headers
}
export type environmentsDashboardsCreateResponse = environmentsDashboardsCreateResponseSuccess

export const getEnvironmentsDashboardsCreateUrl = (projectId: string, params?: EnvironmentsDashboardsCreateParams) => {
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

export const environmentsDashboardsCreate = async (
    projectId: string,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: EnvironmentsDashboardsCreateParams,
    options?: RequestInit
): Promise<environmentsDashboardsCreateResponse> => {
    return apiMutator<environmentsDashboardsCreateResponse>(getEnvironmentsDashboardsCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export type environmentsDashboardsCollaboratorsListResponse200 = {
    data: DashboardCollaboratorApi[]
    status: 200
}

export type environmentsDashboardsCollaboratorsListResponseSuccess =
    environmentsDashboardsCollaboratorsListResponse200 & {
        headers: Headers
    }
export type environmentsDashboardsCollaboratorsListResponse = environmentsDashboardsCollaboratorsListResponseSuccess

export const getEnvironmentsDashboardsCollaboratorsListUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const environmentsDashboardsCollaboratorsList = async (
    projectId: string,
    dashboardId: number,
    options?: RequestInit
): Promise<environmentsDashboardsCollaboratorsListResponse> => {
    return apiMutator<environmentsDashboardsCollaboratorsListResponse>(
        getEnvironmentsDashboardsCollaboratorsListUrl(projectId, dashboardId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsDashboardsCollaboratorsCreateResponse201 = {
    data: DashboardCollaboratorApi
    status: 201
}

export type environmentsDashboardsCollaboratorsCreateResponseSuccess =
    environmentsDashboardsCollaboratorsCreateResponse201 & {
        headers: Headers
    }
export type environmentsDashboardsCollaboratorsCreateResponse = environmentsDashboardsCollaboratorsCreateResponseSuccess

export const getEnvironmentsDashboardsCollaboratorsCreateUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const environmentsDashboardsCollaboratorsCreate = async (
    projectId: string,
    dashboardId: number,
    dashboardCollaboratorApi: NonReadonly<DashboardCollaboratorApi>,
    options?: RequestInit
): Promise<environmentsDashboardsCollaboratorsCreateResponse> => {
    return apiMutator<environmentsDashboardsCollaboratorsCreateResponse>(
        getEnvironmentsDashboardsCollaboratorsCreateUrl(projectId, dashboardId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dashboardCollaboratorApi),
        }
    )
}

export type environmentsDashboardsCollaboratorsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsDashboardsCollaboratorsDestroyResponseSuccess =
    environmentsDashboardsCollaboratorsDestroyResponse204 & {
        headers: Headers
    }
export type environmentsDashboardsCollaboratorsDestroyResponse =
    environmentsDashboardsCollaboratorsDestroyResponseSuccess

export const getEnvironmentsDashboardsCollaboratorsDestroyUrl = (
    projectId: string,
    dashboardId: number,
    userUuid: string
) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/collaborators/${userUuid}/`
}

export const environmentsDashboardsCollaboratorsDestroy = async (
    projectId: string,
    dashboardId: number,
    userUuid: string,
    options?: RequestInit
): Promise<environmentsDashboardsCollaboratorsDestroyResponse> => {
    return apiMutator<environmentsDashboardsCollaboratorsDestroyResponse>(
        getEnvironmentsDashboardsCollaboratorsDestroyUrl(projectId, dashboardId, userUuid),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsDashboardsSharingListResponse200 = {
    data: SharingConfigurationApi[]
    status: 200
}

export type environmentsDashboardsSharingListResponseSuccess = environmentsDashboardsSharingListResponse200 & {
    headers: Headers
}
export type environmentsDashboardsSharingListResponse = environmentsDashboardsSharingListResponseSuccess

export const getEnvironmentsDashboardsSharingListUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/`
}

export const environmentsDashboardsSharingList = async (
    projectId: string,
    dashboardId: number,
    options?: RequestInit
): Promise<environmentsDashboardsSharingListResponse> => {
    return apiMutator<environmentsDashboardsSharingListResponse>(
        getEnvironmentsDashboardsSharingListUrl(projectId, dashboardId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create a new password for the sharing configuration.
 */
export type environmentsDashboardsSharingPasswordsCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type environmentsDashboardsSharingPasswordsCreateResponseSuccess =
    environmentsDashboardsSharingPasswordsCreateResponse200 & {
        headers: Headers
    }
export type environmentsDashboardsSharingPasswordsCreateResponse =
    environmentsDashboardsSharingPasswordsCreateResponseSuccess

export const getEnvironmentsDashboardsSharingPasswordsCreateUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/passwords/`
}

export const environmentsDashboardsSharingPasswordsCreate = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<environmentsDashboardsSharingPasswordsCreateResponse> => {
    return apiMutator<environmentsDashboardsSharingPasswordsCreateResponse>(
        getEnvironmentsDashboardsSharingPasswordsCreateUrl(projectId, dashboardId),
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
export type environmentsDashboardsSharingPasswordsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsDashboardsSharingPasswordsDestroyResponseSuccess =
    environmentsDashboardsSharingPasswordsDestroyResponse204 & {
        headers: Headers
    }
export type environmentsDashboardsSharingPasswordsDestroyResponse =
    environmentsDashboardsSharingPasswordsDestroyResponseSuccess

export const getEnvironmentsDashboardsSharingPasswordsDestroyUrl = (
    projectId: string,
    dashboardId: number,
    passwordId: string
) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/passwords/${passwordId}/`
}

export const environmentsDashboardsSharingPasswordsDestroy = async (
    projectId: string,
    dashboardId: number,
    passwordId: string,
    options?: RequestInit
): Promise<environmentsDashboardsSharingPasswordsDestroyResponse> => {
    return apiMutator<environmentsDashboardsSharingPasswordsDestroyResponse>(
        getEnvironmentsDashboardsSharingPasswordsDestroyUrl(projectId, dashboardId, passwordId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsDashboardsSharingRefreshCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type environmentsDashboardsSharingRefreshCreateResponseSuccess =
    environmentsDashboardsSharingRefreshCreateResponse200 & {
        headers: Headers
    }
export type environmentsDashboardsSharingRefreshCreateResponse =
    environmentsDashboardsSharingRefreshCreateResponseSuccess

export const getEnvironmentsDashboardsSharingRefreshCreateUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/refresh/`
}

export const environmentsDashboardsSharingRefreshCreate = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<environmentsDashboardsSharingRefreshCreateResponse> => {
    return apiMutator<environmentsDashboardsSharingRefreshCreateResponse>(
        getEnvironmentsDashboardsSharingRefreshCreateUrl(projectId, dashboardId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sharingConfigurationApi),
        }
    )
}

export type environmentsDashboardsRetrieveResponse200 = {
    data: DashboardApi
    status: 200
}

export type environmentsDashboardsRetrieveResponseSuccess = environmentsDashboardsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsDashboardsRetrieveResponse = environmentsDashboardsRetrieveResponseSuccess

export const getEnvironmentsDashboardsRetrieveUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsDashboardsRetrieveParams
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

export const environmentsDashboardsRetrieve = async (
    projectId: string,
    id: number,
    params?: EnvironmentsDashboardsRetrieveParams,
    options?: RequestInit
): Promise<environmentsDashboardsRetrieveResponse> => {
    return apiMutator<environmentsDashboardsRetrieveResponse>(
        getEnvironmentsDashboardsRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsDashboardsUpdateResponse200 = {
    data: DashboardApi
    status: 200
}

export type environmentsDashboardsUpdateResponseSuccess = environmentsDashboardsUpdateResponse200 & {
    headers: Headers
}
export type environmentsDashboardsUpdateResponse = environmentsDashboardsUpdateResponseSuccess

export const getEnvironmentsDashboardsUpdateUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsDashboardsUpdateParams
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

export const environmentsDashboardsUpdate = async (
    projectId: string,
    id: number,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: EnvironmentsDashboardsUpdateParams,
    options?: RequestInit
): Promise<environmentsDashboardsUpdateResponse> => {
    return apiMutator<environmentsDashboardsUpdateResponse>(getEnvironmentsDashboardsUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export type environmentsDashboardsPartialUpdateResponse200 = {
    data: DashboardApi
    status: 200
}

export type environmentsDashboardsPartialUpdateResponseSuccess = environmentsDashboardsPartialUpdateResponse200 & {
    headers: Headers
}
export type environmentsDashboardsPartialUpdateResponse = environmentsDashboardsPartialUpdateResponseSuccess

export const getEnvironmentsDashboardsPartialUpdateUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsDashboardsPartialUpdateParams
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

export const environmentsDashboardsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedDashboardApi: NonReadonly<PatchedDashboardApi>,
    params?: EnvironmentsDashboardsPartialUpdateParams,
    options?: RequestInit
): Promise<environmentsDashboardsPartialUpdateResponse> => {
    return apiMutator<environmentsDashboardsPartialUpdateResponse>(
        getEnvironmentsDashboardsPartialUpdateUrl(projectId, id, params),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDashboardApi),
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type environmentsDashboardsDestroyResponse405 = {
    data: void
    status: 405
}
export type environmentsDashboardsDestroyResponseError = environmentsDashboardsDestroyResponse405 & {
    headers: Headers
}

export type environmentsDashboardsDestroyResponse = environmentsDashboardsDestroyResponseError

export const getEnvironmentsDashboardsDestroyUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsDashboardsDestroyParams
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

export const environmentsDashboardsDestroy = async (
    projectId: string,
    id: number,
    params?: EnvironmentsDashboardsDestroyParams,
    options?: RequestInit
): Promise<environmentsDashboardsDestroyResponse> => {
    return apiMutator<environmentsDashboardsDestroyResponse>(
        getEnvironmentsDashboardsDestroyUrl(projectId, id, params),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsDashboardsMoveTilePartialUpdateResponse200 = {
    data: void
    status: 200
}

export type environmentsDashboardsMoveTilePartialUpdateResponseSuccess =
    environmentsDashboardsMoveTilePartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsDashboardsMoveTilePartialUpdateResponse =
    environmentsDashboardsMoveTilePartialUpdateResponseSuccess

export const getEnvironmentsDashboardsMoveTilePartialUpdateUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsDashboardsMoveTilePartialUpdateParams
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

export const environmentsDashboardsMoveTilePartialUpdate = async (
    projectId: string,
    id: number,
    patchedDashboardApi: NonReadonly<PatchedDashboardApi>,
    params?: EnvironmentsDashboardsMoveTilePartialUpdateParams,
    options?: RequestInit
): Promise<environmentsDashboardsMoveTilePartialUpdateResponse> => {
    return apiMutator<environmentsDashboardsMoveTilePartialUpdateResponse>(
        getEnvironmentsDashboardsMoveTilePartialUpdateUrl(projectId, id, params),
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
export type environmentsDashboardsStreamTilesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsDashboardsStreamTilesRetrieveResponseSuccess =
    environmentsDashboardsStreamTilesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsDashboardsStreamTilesRetrieveResponse = environmentsDashboardsStreamTilesRetrieveResponseSuccess

export const getEnvironmentsDashboardsStreamTilesRetrieveUrl = (
    projectId: string,
    id: number,
    params?: EnvironmentsDashboardsStreamTilesRetrieveParams
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

export const environmentsDashboardsStreamTilesRetrieve = async (
    projectId: string,
    id: number,
    params?: EnvironmentsDashboardsStreamTilesRetrieveParams,
    options?: RequestInit
): Promise<environmentsDashboardsStreamTilesRetrieveResponse> => {
    return apiMutator<environmentsDashboardsStreamTilesRetrieveResponse>(
        getEnvironmentsDashboardsStreamTilesRetrieveUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsDashboardsCreateFromTemplateJsonCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsDashboardsCreateFromTemplateJsonCreateResponseSuccess =
    environmentsDashboardsCreateFromTemplateJsonCreateResponse200 & {
        headers: Headers
    }
export type environmentsDashboardsCreateFromTemplateJsonCreateResponse =
    environmentsDashboardsCreateFromTemplateJsonCreateResponseSuccess

export const getEnvironmentsDashboardsCreateFromTemplateJsonCreateUrl = (
    projectId: string,
    params?: EnvironmentsDashboardsCreateFromTemplateJsonCreateParams
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

export const environmentsDashboardsCreateFromTemplateJsonCreate = async (
    projectId: string,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: EnvironmentsDashboardsCreateFromTemplateJsonCreateParams,
    options?: RequestInit
): Promise<environmentsDashboardsCreateFromTemplateJsonCreateResponse> => {
    return apiMutator<environmentsDashboardsCreateFromTemplateJsonCreateResponse>(
        getEnvironmentsDashboardsCreateFromTemplateJsonCreateUrl(projectId, params),
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
export type environmentsDashboardsCreateUnlistedDashboardCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsDashboardsCreateUnlistedDashboardCreateResponseSuccess =
    environmentsDashboardsCreateUnlistedDashboardCreateResponse200 & {
        headers: Headers
    }
export type environmentsDashboardsCreateUnlistedDashboardCreateResponse =
    environmentsDashboardsCreateUnlistedDashboardCreateResponseSuccess

export const getEnvironmentsDashboardsCreateUnlistedDashboardCreateUrl = (
    projectId: string,
    params?: EnvironmentsDashboardsCreateUnlistedDashboardCreateParams
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

export const environmentsDashboardsCreateUnlistedDashboardCreate = async (
    projectId: string,
    dashboardApi: NonReadonly<DashboardApi>,
    params?: EnvironmentsDashboardsCreateUnlistedDashboardCreateParams,
    options?: RequestInit
): Promise<environmentsDashboardsCreateUnlistedDashboardCreateResponse> => {
    return apiMutator<environmentsDashboardsCreateUnlistedDashboardCreateResponse>(
        getEnvironmentsDashboardsCreateUnlistedDashboardCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(dashboardApi),
        }
    )
}

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
        ? `/api/projects/${projectId}/dashboards/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/`
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
        ? `/api/projects/${projectId}/dashboards/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/`
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
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/`
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
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/`
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
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/${userUuid}/`
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
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/`
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
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/passwords/`
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
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/passwords/${passwordId}/`
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
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/refresh/`
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
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
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
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
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
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
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
        ? `/api/projects/${projectId}/dashboards/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/`
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
        ? `/api/projects/${projectId}/dashboards/${id}/move_tile/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/move_tile/`
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
        ? `/api/projects/${projectId}/dashboards/${id}/stream_tiles/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/${id}/stream_tiles/`
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
        ? `/api/projects/${projectId}/dashboards/create_from_template_json/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/create_from_template_json/`
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
        ? `/api/projects/${projectId}/dashboards/create_unlisted_dashboard/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboards/create_unlisted_dashboard/`
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
