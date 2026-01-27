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
): Promise<PaginatedDashboardBasicListApi> => {
    return apiMutator<PaginatedDashboardBasicListApi>(getDashboardsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export const getDashboardsCollaboratorsListUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const dashboardsCollaboratorsList = async (
    projectId: string,
    dashboardId: number,
    options?: RequestInit
): Promise<DashboardCollaboratorApi[]> => {
    return apiMutator<DashboardCollaboratorApi[]>(getDashboardsCollaboratorsListUrl(projectId, dashboardId), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsCollaboratorsCreateUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const dashboardsCollaboratorsCreate = async (
    projectId: string,
    dashboardId: number,
    dashboardCollaboratorApi: NonReadonly<DashboardCollaboratorApi>,
    options?: RequestInit
): Promise<DashboardCollaboratorApi> => {
    return apiMutator<DashboardCollaboratorApi>(getDashboardsCollaboratorsCreateUrl(projectId, dashboardId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardCollaboratorApi),
    })
}

export const getDashboardsCollaboratorsDestroyUrl = (projectId: string, dashboardId: number, userUuid: string) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/collaborators/${userUuid}/`
}

export const dashboardsCollaboratorsDestroy = async (
    projectId: string,
    dashboardId: number,
    userUuid: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDashboardsCollaboratorsDestroyUrl(projectId, dashboardId, userUuid), {
        ...options,
        method: 'DELETE',
    })
}

export const getDashboardsSharingListUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/`
}

export const dashboardsSharingList = async (
    projectId: string,
    dashboardId: number,
    options?: RequestInit
): Promise<SharingConfigurationApi[]> => {
    return apiMutator<SharingConfigurationApi[]>(getDashboardsSharingListUrl(projectId, dashboardId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new password for the sharing configuration.
 */
export const getDashboardsSharingPasswordsCreateUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/passwords/`
}

export const dashboardsSharingPasswordsCreate = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getDashboardsSharingPasswordsCreateUrl(projectId, dashboardId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

/**
 * Delete a password from the sharing configuration.
 */
export const getDashboardsSharingPasswordsDestroyUrl = (projectId: string, dashboardId: number, passwordId: string) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/passwords/${passwordId}/`
}

export const dashboardsSharingPasswordsDestroy = async (
    projectId: string,
    dashboardId: number,
    passwordId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDashboardsSharingPasswordsDestroyUrl(projectId, dashboardId, passwordId), {
        ...options,
        method: 'DELETE',
    })
}

export const getDashboardsSharingRefreshCreateUrl = (projectId: string, dashboardId: number) => {
    return `/api/environments/${projectId}/dashboards/${dashboardId}/sharing/refresh/`
}

export const dashboardsSharingRefreshCreate = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getDashboardsSharingRefreshCreateUrl(projectId, dashboardId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

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
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

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
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsPartialUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDashboardApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
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
): Promise<unknown> => {
    return apiMutator<unknown>(getDashboardsDestroyUrl(projectId, id, params), {
        ...options,
        method: 'DELETE',
    })
}

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
): Promise<void> => {
    return apiMutator<void>(getDashboardsMoveTilePartialUpdateUrl(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDashboardApi),
    })
}

/**
 * Stream dashboard metadata and tiles via Server-Sent Events. Sends metadata first, then tiles as they are rendered.
 */
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
): Promise<void> => {
    return apiMutator<void>(getDashboardsStreamTilesRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<void> => {
    return apiMutator<void>(getDashboardsCreateFromTemplateJsonCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

/**
 * Creates an unlisted dashboard from template by tag.
Enforces uniqueness (one per tag per team).
Returns 409 if unlisted dashboard with this tag already exists.
 */
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
): Promise<void> => {
    return apiMutator<void>(getDashboardsCreateUnlistedDashboardCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

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
): Promise<PaginatedDataColorThemeListApi> => {
    return apiMutator<PaginatedDataColorThemeListApi>(getDataColorThemesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataColorThemesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/data_color_themes/`
}

export const dataColorThemesCreate = async (
    projectId: string,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataColorThemeApi),
    })
}

export const getDataColorThemesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDataColorThemesUpdateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesUpdate = async (
    projectId: string,
    id: number,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataColorThemeApi),
    })
}

export const getDataColorThemesPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesPartialUpdate = async (
    projectId: string,
    id: number,
    patchedDataColorThemeApi: NonReadonly<PatchedDataColorThemeApi>,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataColorThemeApi),
    })
}

export const getDataColorThemesDestroyUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataColorThemesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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
): Promise<PaginatedDashboardBasicListApi> => {
    return apiMutator<PaginatedDashboardBasicListApi>(getDashboardsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsCreate2Url(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

export const getDashboardsCollaboratorsList2Url = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const dashboardsCollaboratorsList2 = async (
    projectId: string,
    dashboardId: number,
    options?: RequestInit
): Promise<DashboardCollaboratorApi[]> => {
    return apiMutator<DashboardCollaboratorApi[]>(getDashboardsCollaboratorsList2Url(projectId, dashboardId), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsCollaboratorsCreate2Url = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/`
}

export const dashboardsCollaboratorsCreate2 = async (
    projectId: string,
    dashboardId: number,
    dashboardCollaboratorApi: NonReadonly<DashboardCollaboratorApi>,
    options?: RequestInit
): Promise<DashboardCollaboratorApi> => {
    return apiMutator<DashboardCollaboratorApi>(getDashboardsCollaboratorsCreate2Url(projectId, dashboardId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardCollaboratorApi),
    })
}

export const getDashboardsCollaboratorsDestroy2Url = (projectId: string, dashboardId: number, userUuid: string) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/collaborators/${userUuid}/`
}

export const dashboardsCollaboratorsDestroy2 = async (
    projectId: string,
    dashboardId: number,
    userUuid: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDashboardsCollaboratorsDestroy2Url(projectId, dashboardId, userUuid), {
        ...options,
        method: 'DELETE',
    })
}

export const getDashboardsSharingList2Url = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/`
}

export const dashboardsSharingList2 = async (
    projectId: string,
    dashboardId: number,
    options?: RequestInit
): Promise<SharingConfigurationApi[]> => {
    return apiMutator<SharingConfigurationApi[]>(getDashboardsSharingList2Url(projectId, dashboardId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new password for the sharing configuration.
 */
export const getDashboardsSharingPasswordsCreate2Url = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/passwords/`
}

export const dashboardsSharingPasswordsCreate2 = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getDashboardsSharingPasswordsCreate2Url(projectId, dashboardId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

/**
 * Delete a password from the sharing configuration.
 */
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
): Promise<void> => {
    return apiMutator<void>(getDashboardsSharingPasswordsDestroy2Url(projectId, dashboardId, passwordId), {
        ...options,
        method: 'DELETE',
    })
}

export const getDashboardsSharingRefreshCreate2Url = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/refresh/`
}

export const dashboardsSharingRefreshCreate2 = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getDashboardsSharingRefreshCreate2Url(projectId, dashboardId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

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
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsRetrieve2Url(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsUpdate2Url(projectId, id, params), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

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
): Promise<DashboardApi> => {
    return apiMutator<DashboardApi>(getDashboardsPartialUpdate2Url(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDashboardApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
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
): Promise<unknown> => {
    return apiMutator<unknown>(getDashboardsDestroy2Url(projectId, id, params), {
        ...options,
        method: 'DELETE',
    })
}

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
): Promise<void> => {
    return apiMutator<void>(getDashboardsMoveTilePartialUpdate2Url(projectId, id, params), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDashboardApi),
    })
}

/**
 * Stream dashboard metadata and tiles via Server-Sent Events. Sends metadata first, then tiles as they are rendered.
 */
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
): Promise<void> => {
    return apiMutator<void>(getDashboardsStreamTilesRetrieve2Url(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<void> => {
    return apiMutator<void>(getDashboardsCreateFromTemplateJsonCreate2Url(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

/**
 * Creates an unlisted dashboard from template by tag.
Enforces uniqueness (one per tag per team).
Returns 409 if unlisted dashboard with this tag already exists.
 */
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
): Promise<void> => {
    return apiMutator<void>(getDashboardsCreateUnlistedDashboardCreate2Url(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardApi),
    })
}

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
): Promise<PaginatedDataColorThemeListApi> => {
    return apiMutator<PaginatedDataColorThemeListApi>(getDataColorThemesList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDataColorThemesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/data_color_themes/`
}

export const dataColorThemesCreate2 = async (
    projectId: string,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataColorThemeApi),
    })
}

export const getDataColorThemesRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDataColorThemesUpdate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesUpdate2 = async (
    projectId: string,
    id: number,
    dataColorThemeApi: NonReadonly<DataColorThemeApi>,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dataColorThemeApi),
    })
}

export const getDataColorThemesPartialUpdate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesPartialUpdate2 = async (
    projectId: string,
    id: number,
    patchedDataColorThemeApi: NonReadonly<PatchedDataColorThemeApi>,
    options?: RequestInit
): Promise<DataColorThemeApi> => {
    return apiMutator<DataColorThemeApi>(getDataColorThemesPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDataColorThemeApi),
    })
}

export const getDataColorThemesDestroy2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/data_color_themes/${id}/`
}

export const dataColorThemesDestroy2 = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDataColorThemesDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
