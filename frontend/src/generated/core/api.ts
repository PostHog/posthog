/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - core
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../lib/api-orval-mutator'
import type {
    AnnotationApi,
    AnnotationsListParams,
    CohortApi,
    CohortsListParams,
    CohortsPersonsRetrieveParams,
    CommentApi,
    CommentsListParams,
    CreateGroupApi,
    DashboardApi,
    DashboardTemplateApi,
    DashboardTemplatesListParams,
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
    DomainsListParams,
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
    EnvironmentsExportsListParams,
    EnvironmentsFileSystemListParams,
    EnvironmentsGroupsActivityRetrieveParams,
    EnvironmentsGroupsDeletePropertyCreateParams,
    EnvironmentsGroupsFindRetrieveParams,
    EnvironmentsGroupsListParams,
    EnvironmentsGroupsRelatedRetrieveParams,
    EnvironmentsGroupsUpdatePropertyCreateParams,
    EnvironmentsIntegrationsListParams,
    EnvironmentsSubscriptionsListParams,
    ExportedAssetApi,
    ExportsListParams,
    FileSystemApi,
    FileSystemListParams,
    GroupApi,
    GroupsActivityRetrieveParams,
    GroupsDeletePropertyCreateParams,
    GroupsFindRetrieveParams,
    GroupsListParams,
    GroupsRelatedRetrieveParams,
    GroupsUpdatePropertyCreateParams,
    IntegrationApi,
    IntegrationsList2Params,
    InvitesListParams,
    List2Params,
    MembersListParams,
    OrganizationDomainApi,
    OrganizationInviteApi,
    OrganizationMemberApi,
    PaginatedAnnotationListApi,
    PaginatedCohortListApi,
    PaginatedCommentListApi,
    PaginatedDashboardBasicListApi,
    PaginatedDashboardTemplateListApi,
    PaginatedExportedAssetListApi,
    PaginatedFileSystemListApi,
    PaginatedGroupListApi,
    PaginatedIntegrationListApi,
    PaginatedOrganizationDomainListApi,
    PaginatedOrganizationInviteListApi,
    PaginatedOrganizationMemberListApi,
    PaginatedProjectBackwardCompatBasicListApi,
    PaginatedPropertyDefinitionListApi,
    PaginatedRoleListApi,
    PaginatedScheduledChangeListApi,
    PaginatedSubscriptionListApi,
    PaginatedUserListApi,
    PatchedAddPersonsToStaticCohortRequestApi,
    PatchedAnnotationApi,
    PatchedCohortApi,
    PatchedCommentApi,
    PatchedDashboardApi,
    PatchedDashboardTemplateApi,
    PatchedFileSystemApi,
    PatchedOrganizationDomainApi,
    PatchedOrganizationMemberApi,
    PatchedProjectBackwardCompatApi,
    PatchedPropertyDefinitionApi,
    PatchedRemovePersonRequestApi,
    PatchedRoleApi,
    PatchedScheduledChangeApi,
    PatchedSubscriptionApi,
    PatchedUserApi,
    ProjectBackwardCompatApi,
    PropertyDefinitionApi,
    PropertyDefinitionsListParams,
    RoleApi,
    RolesListParams,
    ScheduledChangeApi,
    ScheduledChangesListParams,
    SharingConfigurationApi,
    SubscriptionApi,
    SubscriptionsListParams,
    UserApi,
    UsersListParams,
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

export type environmentsExportsListResponse200 = {
    data: PaginatedExportedAssetListApi
    status: 200
}

export type environmentsExportsListResponseSuccess = environmentsExportsListResponse200 & {
    headers: Headers
}
export type environmentsExportsListResponse = environmentsExportsListResponseSuccess

export const getEnvironmentsExportsListUrl = (projectId: string, params?: EnvironmentsExportsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/exports/?${stringifiedParams}`
        : `/api/environments/${projectId}/exports/`
}

export const environmentsExportsList = async (
    projectId: string,
    params?: EnvironmentsExportsListParams,
    options?: RequestInit
): Promise<environmentsExportsListResponse> => {
    return apiMutator<environmentsExportsListResponse>(getEnvironmentsExportsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsExportsCreateResponse201 = {
    data: ExportedAssetApi
    status: 201
}

export type environmentsExportsCreateResponseSuccess = environmentsExportsCreateResponse201 & {
    headers: Headers
}
export type environmentsExportsCreateResponse = environmentsExportsCreateResponseSuccess

export const getEnvironmentsExportsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/exports/`
}

export const environmentsExportsCreate = async (
    projectId: string,
    exportedAssetApi: NonReadonly<ExportedAssetApi>,
    options?: RequestInit
): Promise<environmentsExportsCreateResponse> => {
    return apiMutator<environmentsExportsCreateResponse>(getEnvironmentsExportsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(exportedAssetApi),
    })
}

export type environmentsExportsRetrieveResponse200 = {
    data: ExportedAssetApi
    status: 200
}

export type environmentsExportsRetrieveResponseSuccess = environmentsExportsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsExportsRetrieveResponse = environmentsExportsRetrieveResponseSuccess

export const getEnvironmentsExportsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/exports/${id}/`
}

export const environmentsExportsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsExportsRetrieveResponse> => {
    return apiMutator<environmentsExportsRetrieveResponse>(getEnvironmentsExportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type environmentsExportsContentRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsExportsContentRetrieveResponseSuccess = environmentsExportsContentRetrieveResponse200 & {
    headers: Headers
}
export type environmentsExportsContentRetrieveResponse = environmentsExportsContentRetrieveResponseSuccess

export const getEnvironmentsExportsContentRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/exports/${id}/content/`
}

export const environmentsExportsContentRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsExportsContentRetrieveResponse> => {
    return apiMutator<environmentsExportsContentRetrieveResponse>(
        getEnvironmentsExportsContentRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsFileSystemListResponse200 = {
    data: PaginatedFileSystemListApi
    status: 200
}

export type environmentsFileSystemListResponseSuccess = environmentsFileSystemListResponse200 & {
    headers: Headers
}
export type environmentsFileSystemListResponse = environmentsFileSystemListResponseSuccess

export const getEnvironmentsFileSystemListUrl = (projectId: string, params?: EnvironmentsFileSystemListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/file_system/?${stringifiedParams}`
        : `/api/environments/${projectId}/file_system/`
}

export const environmentsFileSystemList = async (
    projectId: string,
    params?: EnvironmentsFileSystemListParams,
    options?: RequestInit
): Promise<environmentsFileSystemListResponse> => {
    return apiMutator<environmentsFileSystemListResponse>(getEnvironmentsFileSystemListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsFileSystemCreateResponse201 = {
    data: FileSystemApi
    status: 201
}

export type environmentsFileSystemCreateResponseSuccess = environmentsFileSystemCreateResponse201 & {
    headers: Headers
}
export type environmentsFileSystemCreateResponse = environmentsFileSystemCreateResponseSuccess

export const getEnvironmentsFileSystemCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/file_system/`
}

export const environmentsFileSystemCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<environmentsFileSystemCreateResponse> => {
    return apiMutator<environmentsFileSystemCreateResponse>(getEnvironmentsFileSystemCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type environmentsFileSystemRetrieveResponse200 = {
    data: FileSystemApi
    status: 200
}

export type environmentsFileSystemRetrieveResponseSuccess = environmentsFileSystemRetrieveResponse200 & {
    headers: Headers
}
export type environmentsFileSystemRetrieveResponse = environmentsFileSystemRetrieveResponseSuccess

export const getEnvironmentsFileSystemRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/file_system/${id}/`
}

export const environmentsFileSystemRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsFileSystemRetrieveResponse> => {
    return apiMutator<environmentsFileSystemRetrieveResponse>(getEnvironmentsFileSystemRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type environmentsFileSystemUpdateResponse200 = {
    data: FileSystemApi
    status: 200
}

export type environmentsFileSystemUpdateResponseSuccess = environmentsFileSystemUpdateResponse200 & {
    headers: Headers
}
export type environmentsFileSystemUpdateResponse = environmentsFileSystemUpdateResponseSuccess

export const getEnvironmentsFileSystemUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/file_system/${id}/`
}

export const environmentsFileSystemUpdate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<environmentsFileSystemUpdateResponse> => {
    return apiMutator<environmentsFileSystemUpdateResponse>(getEnvironmentsFileSystemUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type environmentsFileSystemPartialUpdateResponse200 = {
    data: FileSystemApi
    status: 200
}

export type environmentsFileSystemPartialUpdateResponseSuccess = environmentsFileSystemPartialUpdateResponse200 & {
    headers: Headers
}
export type environmentsFileSystemPartialUpdateResponse = environmentsFileSystemPartialUpdateResponseSuccess

export const getEnvironmentsFileSystemPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/file_system/${id}/`
}

export const environmentsFileSystemPartialUpdate = async (
    projectId: string,
    id: string,
    patchedFileSystemApi: NonReadonly<PatchedFileSystemApi>,
    options?: RequestInit
): Promise<environmentsFileSystemPartialUpdateResponse> => {
    return apiMutator<environmentsFileSystemPartialUpdateResponse>(
        getEnvironmentsFileSystemPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedFileSystemApi),
        }
    )
}

export type environmentsFileSystemDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsFileSystemDestroyResponseSuccess = environmentsFileSystemDestroyResponse204 & {
    headers: Headers
}
export type environmentsFileSystemDestroyResponse = environmentsFileSystemDestroyResponseSuccess

export const getEnvironmentsFileSystemDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/file_system/${id}/`
}

export const environmentsFileSystemDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsFileSystemDestroyResponse> => {
    return apiMutator<environmentsFileSystemDestroyResponse>(getEnvironmentsFileSystemDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Get count of all files in a folder.
 */
export type environmentsFileSystemCountCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsFileSystemCountCreateResponseSuccess = environmentsFileSystemCountCreateResponse200 & {
    headers: Headers
}
export type environmentsFileSystemCountCreateResponse = environmentsFileSystemCountCreateResponseSuccess

export const getEnvironmentsFileSystemCountCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/file_system/${id}/count/`
}

export const environmentsFileSystemCountCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<environmentsFileSystemCountCreateResponse> => {
    return apiMutator<environmentsFileSystemCountCreateResponse>(
        getEnvironmentsFileSystemCountCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(fileSystemApi),
        }
    )
}

export type environmentsFileSystemLinkCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsFileSystemLinkCreateResponseSuccess = environmentsFileSystemLinkCreateResponse200 & {
    headers: Headers
}
export type environmentsFileSystemLinkCreateResponse = environmentsFileSystemLinkCreateResponseSuccess

export const getEnvironmentsFileSystemLinkCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/file_system/${id}/link/`
}

export const environmentsFileSystemLinkCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<environmentsFileSystemLinkCreateResponse> => {
    return apiMutator<environmentsFileSystemLinkCreateResponse>(getEnvironmentsFileSystemLinkCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type environmentsFileSystemMoveCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsFileSystemMoveCreateResponseSuccess = environmentsFileSystemMoveCreateResponse200 & {
    headers: Headers
}
export type environmentsFileSystemMoveCreateResponse = environmentsFileSystemMoveCreateResponseSuccess

export const getEnvironmentsFileSystemMoveCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/file_system/${id}/move/`
}

export const environmentsFileSystemMoveCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<environmentsFileSystemMoveCreateResponse> => {
    return apiMutator<environmentsFileSystemMoveCreateResponse>(getEnvironmentsFileSystemMoveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

/**
 * Get count of all files in a folder.
 */
export type environmentsFileSystemCountByPathCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsFileSystemCountByPathCreateResponseSuccess =
    environmentsFileSystemCountByPathCreateResponse200 & {
        headers: Headers
    }
export type environmentsFileSystemCountByPathCreateResponse = environmentsFileSystemCountByPathCreateResponseSuccess

export const getEnvironmentsFileSystemCountByPathCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/file_system/count_by_path/`
}

export const environmentsFileSystemCountByPathCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<environmentsFileSystemCountByPathCreateResponse> => {
    return apiMutator<environmentsFileSystemCountByPathCreateResponse>(
        getEnvironmentsFileSystemCountByPathCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(fileSystemApi),
        }
    )
}

export type environmentsFileSystemLogViewRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsFileSystemLogViewRetrieveResponseSuccess = environmentsFileSystemLogViewRetrieveResponse200 & {
    headers: Headers
}
export type environmentsFileSystemLogViewRetrieveResponse = environmentsFileSystemLogViewRetrieveResponseSuccess

export const getEnvironmentsFileSystemLogViewRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/file_system/log_view/`
}

export const environmentsFileSystemLogViewRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsFileSystemLogViewRetrieveResponse> => {
    return apiMutator<environmentsFileSystemLogViewRetrieveResponse>(
        getEnvironmentsFileSystemLogViewRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsFileSystemLogViewCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsFileSystemLogViewCreateResponseSuccess = environmentsFileSystemLogViewCreateResponse200 & {
    headers: Headers
}
export type environmentsFileSystemLogViewCreateResponse = environmentsFileSystemLogViewCreateResponseSuccess

export const getEnvironmentsFileSystemLogViewCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/file_system/log_view/`
}

export const environmentsFileSystemLogViewCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<environmentsFileSystemLogViewCreateResponse> => {
    return apiMutator<environmentsFileSystemLogViewCreateResponse>(
        getEnvironmentsFileSystemLogViewCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(fileSystemApi),
        }
    )
}

export type environmentsFileSystemUndoDeleteCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsFileSystemUndoDeleteCreateResponseSuccess =
    environmentsFileSystemUndoDeleteCreateResponse200 & {
        headers: Headers
    }
export type environmentsFileSystemUndoDeleteCreateResponse = environmentsFileSystemUndoDeleteCreateResponseSuccess

export const getEnvironmentsFileSystemUndoDeleteCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/file_system/undo_delete/`
}

export const environmentsFileSystemUndoDeleteCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<environmentsFileSystemUndoDeleteCreateResponse> => {
    return apiMutator<environmentsFileSystemUndoDeleteCreateResponse>(
        getEnvironmentsFileSystemUndoDeleteCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(fileSystemApi),
        }
    )
}

export type environmentsFileSystemUnfiledRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsFileSystemUnfiledRetrieveResponseSuccess = environmentsFileSystemUnfiledRetrieveResponse200 & {
    headers: Headers
}
export type environmentsFileSystemUnfiledRetrieveResponse = environmentsFileSystemUnfiledRetrieveResponseSuccess

export const getEnvironmentsFileSystemUnfiledRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/file_system/unfiled/`
}

export const environmentsFileSystemUnfiledRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsFileSystemUnfiledRetrieveResponse> => {
    return apiMutator<environmentsFileSystemUnfiledRetrieveResponse>(
        getEnvironmentsFileSystemUnfiledRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * List all groups of a specific group type. You must pass ?group_type_index= in the URL. To get a list of valid group types, call /api/:project_id/groups_types/
 */
export type environmentsGroupsListResponse200 = {
    data: PaginatedGroupListApi
    status: 200
}

export type environmentsGroupsListResponseSuccess = environmentsGroupsListResponse200 & {
    headers: Headers
}
export type environmentsGroupsListResponse = environmentsGroupsListResponseSuccess

export const getEnvironmentsGroupsListUrl = (projectId: string, params: EnvironmentsGroupsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/`
}

export const environmentsGroupsList = async (
    projectId: string,
    params: EnvironmentsGroupsListParams,
    options?: RequestInit
): Promise<environmentsGroupsListResponse> => {
    return apiMutator<environmentsGroupsListResponse>(getEnvironmentsGroupsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsGroupsCreateResponse201 = {
    data: GroupApi
    status: 201
}

export type environmentsGroupsCreateResponseSuccess = environmentsGroupsCreateResponse201 & {
    headers: Headers
}
export type environmentsGroupsCreateResponse = environmentsGroupsCreateResponseSuccess

export const getEnvironmentsGroupsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/groups/`
}

export const environmentsGroupsCreate = async (
    projectId: string,
    createGroupApi: CreateGroupApi,
    options?: RequestInit
): Promise<environmentsGroupsCreateResponse> => {
    return apiMutator<environmentsGroupsCreateResponse>(getEnvironmentsGroupsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createGroupApi),
    })
}

export type environmentsGroupsActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsActivityRetrieveResponseSuccess = environmentsGroupsActivityRetrieveResponse200 & {
    headers: Headers
}
export type environmentsGroupsActivityRetrieveResponse = environmentsGroupsActivityRetrieveResponseSuccess

export const getEnvironmentsGroupsActivityRetrieveUrl = (
    projectId: string,
    params: EnvironmentsGroupsActivityRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/activity/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/activity/`
}

export const environmentsGroupsActivityRetrieve = async (
    projectId: string,
    params: EnvironmentsGroupsActivityRetrieveParams,
    options?: RequestInit
): Promise<environmentsGroupsActivityRetrieveResponse> => {
    return apiMutator<environmentsGroupsActivityRetrieveResponse>(
        getEnvironmentsGroupsActivityRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsGroupsDeletePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsDeletePropertyCreateResponseSuccess =
    environmentsGroupsDeletePropertyCreateResponse200 & {
        headers: Headers
    }
export type environmentsGroupsDeletePropertyCreateResponse = environmentsGroupsDeletePropertyCreateResponseSuccess

export const getEnvironmentsGroupsDeletePropertyCreateUrl = (
    projectId: string,
    params: EnvironmentsGroupsDeletePropertyCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/delete_property/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/delete_property/`
}

export const environmentsGroupsDeletePropertyCreate = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: EnvironmentsGroupsDeletePropertyCreateParams,
    options?: RequestInit
): Promise<environmentsGroupsDeletePropertyCreateResponse> => {
    return apiMutator<environmentsGroupsDeletePropertyCreateResponse>(
        getEnvironmentsGroupsDeletePropertyCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(groupApi),
        }
    )
}

export type environmentsGroupsFindRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsFindRetrieveResponseSuccess = environmentsGroupsFindRetrieveResponse200 & {
    headers: Headers
}
export type environmentsGroupsFindRetrieveResponse = environmentsGroupsFindRetrieveResponseSuccess

export const getEnvironmentsGroupsFindRetrieveUrl = (
    projectId: string,
    params: EnvironmentsGroupsFindRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/find/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/find/`
}

export const environmentsGroupsFindRetrieve = async (
    projectId: string,
    params: EnvironmentsGroupsFindRetrieveParams,
    options?: RequestInit
): Promise<environmentsGroupsFindRetrieveResponse> => {
    return apiMutator<environmentsGroupsFindRetrieveResponse>(getEnvironmentsGroupsFindRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsGroupsPropertyDefinitionsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsPropertyDefinitionsRetrieveResponseSuccess =
    environmentsGroupsPropertyDefinitionsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsGroupsPropertyDefinitionsRetrieveResponse =
    environmentsGroupsPropertyDefinitionsRetrieveResponseSuccess

export const getEnvironmentsGroupsPropertyDefinitionsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/groups/property_definitions/`
}

export const environmentsGroupsPropertyDefinitionsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsGroupsPropertyDefinitionsRetrieveResponse> => {
    return apiMutator<environmentsGroupsPropertyDefinitionsRetrieveResponse>(
        getEnvironmentsGroupsPropertyDefinitionsRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsGroupsPropertyValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsPropertyValuesRetrieveResponseSuccess =
    environmentsGroupsPropertyValuesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsGroupsPropertyValuesRetrieveResponse = environmentsGroupsPropertyValuesRetrieveResponseSuccess

export const getEnvironmentsGroupsPropertyValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/groups/property_values/`
}

export const environmentsGroupsPropertyValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsGroupsPropertyValuesRetrieveResponse> => {
    return apiMutator<environmentsGroupsPropertyValuesRetrieveResponse>(
        getEnvironmentsGroupsPropertyValuesRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsGroupsRelatedRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsRelatedRetrieveResponseSuccess = environmentsGroupsRelatedRetrieveResponse200 & {
    headers: Headers
}
export type environmentsGroupsRelatedRetrieveResponse = environmentsGroupsRelatedRetrieveResponseSuccess

export const getEnvironmentsGroupsRelatedRetrieveUrl = (
    projectId: string,
    params: EnvironmentsGroupsRelatedRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/related/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/related/`
}

export const environmentsGroupsRelatedRetrieve = async (
    projectId: string,
    params: EnvironmentsGroupsRelatedRetrieveParams,
    options?: RequestInit
): Promise<environmentsGroupsRelatedRetrieveResponse> => {
    return apiMutator<environmentsGroupsRelatedRetrieveResponse>(
        getEnvironmentsGroupsRelatedRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsGroupsUpdatePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsUpdatePropertyCreateResponseSuccess =
    environmentsGroupsUpdatePropertyCreateResponse200 & {
        headers: Headers
    }
export type environmentsGroupsUpdatePropertyCreateResponse = environmentsGroupsUpdatePropertyCreateResponseSuccess

export const getEnvironmentsGroupsUpdatePropertyCreateUrl = (
    projectId: string,
    params: EnvironmentsGroupsUpdatePropertyCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/update_property/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/update_property/`
}

export const environmentsGroupsUpdatePropertyCreate = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: EnvironmentsGroupsUpdatePropertyCreateParams,
    options?: RequestInit
): Promise<environmentsGroupsUpdatePropertyCreateResponse> => {
    return apiMutator<environmentsGroupsUpdatePropertyCreateResponse>(
        getEnvironmentsGroupsUpdatePropertyCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(groupApi),
        }
    )
}

export type environmentsInsightsSharingListResponse200 = {
    data: SharingConfigurationApi[]
    status: 200
}

export type environmentsInsightsSharingListResponseSuccess = environmentsInsightsSharingListResponse200 & {
    headers: Headers
}
export type environmentsInsightsSharingListResponse = environmentsInsightsSharingListResponseSuccess

export const getEnvironmentsInsightsSharingListUrl = (projectId: string, insightId: number) => {
    return `/api/environments/${projectId}/insights/${insightId}/sharing/`
}

export const environmentsInsightsSharingList = async (
    projectId: string,
    insightId: number,
    options?: RequestInit
): Promise<environmentsInsightsSharingListResponse> => {
    return apiMutator<environmentsInsightsSharingListResponse>(
        getEnvironmentsInsightsSharingListUrl(projectId, insightId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create a new password for the sharing configuration.
 */
export type environmentsInsightsSharingPasswordsCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type environmentsInsightsSharingPasswordsCreateResponseSuccess =
    environmentsInsightsSharingPasswordsCreateResponse200 & {
        headers: Headers
    }
export type environmentsInsightsSharingPasswordsCreateResponse =
    environmentsInsightsSharingPasswordsCreateResponseSuccess

export const getEnvironmentsInsightsSharingPasswordsCreateUrl = (projectId: string, insightId: number) => {
    return `/api/environments/${projectId}/insights/${insightId}/sharing/passwords/`
}

export const environmentsInsightsSharingPasswordsCreate = async (
    projectId: string,
    insightId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<environmentsInsightsSharingPasswordsCreateResponse> => {
    return apiMutator<environmentsInsightsSharingPasswordsCreateResponse>(
        getEnvironmentsInsightsSharingPasswordsCreateUrl(projectId, insightId),
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
export type environmentsInsightsSharingPasswordsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsInsightsSharingPasswordsDestroyResponseSuccess =
    environmentsInsightsSharingPasswordsDestroyResponse204 & {
        headers: Headers
    }
export type environmentsInsightsSharingPasswordsDestroyResponse =
    environmentsInsightsSharingPasswordsDestroyResponseSuccess

export const getEnvironmentsInsightsSharingPasswordsDestroyUrl = (
    projectId: string,
    insightId: number,
    passwordId: string
) => {
    return `/api/environments/${projectId}/insights/${insightId}/sharing/passwords/${passwordId}/`
}

export const environmentsInsightsSharingPasswordsDestroy = async (
    projectId: string,
    insightId: number,
    passwordId: string,
    options?: RequestInit
): Promise<environmentsInsightsSharingPasswordsDestroyResponse> => {
    return apiMutator<environmentsInsightsSharingPasswordsDestroyResponse>(
        getEnvironmentsInsightsSharingPasswordsDestroyUrl(projectId, insightId, passwordId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsInsightsSharingRefreshCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type environmentsInsightsSharingRefreshCreateResponseSuccess =
    environmentsInsightsSharingRefreshCreateResponse200 & {
        headers: Headers
    }
export type environmentsInsightsSharingRefreshCreateResponse = environmentsInsightsSharingRefreshCreateResponseSuccess

export const getEnvironmentsInsightsSharingRefreshCreateUrl = (projectId: string, insightId: number) => {
    return `/api/environments/${projectId}/insights/${insightId}/sharing/refresh/`
}

export const environmentsInsightsSharingRefreshCreate = async (
    projectId: string,
    insightId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<environmentsInsightsSharingRefreshCreateResponse> => {
    return apiMutator<environmentsInsightsSharingRefreshCreateResponse>(
        getEnvironmentsInsightsSharingRefreshCreateUrl(projectId, insightId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sharingConfigurationApi),
        }
    )
}

export type environmentsIntegrationsListResponse200 = {
    data: PaginatedIntegrationListApi
    status: 200
}

export type environmentsIntegrationsListResponseSuccess = environmentsIntegrationsListResponse200 & {
    headers: Headers
}
export type environmentsIntegrationsListResponse = environmentsIntegrationsListResponseSuccess

export const getEnvironmentsIntegrationsListUrl = (projectId: string, params?: EnvironmentsIntegrationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/integrations/?${stringifiedParams}`
        : `/api/environments/${projectId}/integrations/`
}

export const environmentsIntegrationsList = async (
    projectId: string,
    params?: EnvironmentsIntegrationsListParams,
    options?: RequestInit
): Promise<environmentsIntegrationsListResponse> => {
    return apiMutator<environmentsIntegrationsListResponse>(getEnvironmentsIntegrationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsIntegrationsCreateResponse201 = {
    data: IntegrationApi
    status: 201
}

export type environmentsIntegrationsCreateResponseSuccess = environmentsIntegrationsCreateResponse201 & {
    headers: Headers
}
export type environmentsIntegrationsCreateResponse = environmentsIntegrationsCreateResponseSuccess

export const getEnvironmentsIntegrationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/integrations/`
}

export const environmentsIntegrationsCreate = async (
    projectId: string,
    integrationApi: NonReadonly<IntegrationApi>,
    options?: RequestInit
): Promise<environmentsIntegrationsCreateResponse> => {
    return apiMutator<environmentsIntegrationsCreateResponse>(getEnvironmentsIntegrationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationApi),
    })
}

export type environmentsIntegrationsRetrieveResponse200 = {
    data: IntegrationApi
    status: 200
}

export type environmentsIntegrationsRetrieveResponseSuccess = environmentsIntegrationsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsIntegrationsRetrieveResponse = environmentsIntegrationsRetrieveResponseSuccess

export const getEnvironmentsIntegrationsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/`
}

export const environmentsIntegrationsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsRetrieveResponse>(getEnvironmentsIntegrationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type environmentsIntegrationsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsIntegrationsDestroyResponseSuccess = environmentsIntegrationsDestroyResponse204 & {
    headers: Headers
}
export type environmentsIntegrationsDestroyResponse = environmentsIntegrationsDestroyResponseSuccess

export const getEnvironmentsIntegrationsDestroyUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/`
}

export const environmentsIntegrationsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsDestroyResponse> => {
    return apiMutator<environmentsIntegrationsDestroyResponse>(getEnvironmentsIntegrationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type environmentsIntegrationsChannelsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsChannelsRetrieveResponseSuccess =
    environmentsIntegrationsChannelsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsChannelsRetrieveResponse = environmentsIntegrationsChannelsRetrieveResponseSuccess

export const getEnvironmentsIntegrationsChannelsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/channels/`
}

export const environmentsIntegrationsChannelsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsChannelsRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsChannelsRetrieveResponse>(
        getEnvironmentsIntegrationsChannelsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsClickupListsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsClickupListsRetrieveResponseSuccess =
    environmentsIntegrationsClickupListsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsClickupListsRetrieveResponse =
    environmentsIntegrationsClickupListsRetrieveResponseSuccess

export const getEnvironmentsIntegrationsClickupListsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/clickup_lists/`
}

export const environmentsIntegrationsClickupListsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsClickupListsRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsClickupListsRetrieveResponse>(
        getEnvironmentsIntegrationsClickupListsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsClickupSpacesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsClickupSpacesRetrieveResponseSuccess =
    environmentsIntegrationsClickupSpacesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsClickupSpacesRetrieveResponse =
    environmentsIntegrationsClickupSpacesRetrieveResponseSuccess

export const getEnvironmentsIntegrationsClickupSpacesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/clickup_spaces/`
}

export const environmentsIntegrationsClickupSpacesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsClickupSpacesRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsClickupSpacesRetrieveResponse>(
        getEnvironmentsIntegrationsClickupSpacesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsClickupWorkspacesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsClickupWorkspacesRetrieveResponseSuccess =
    environmentsIntegrationsClickupWorkspacesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsClickupWorkspacesRetrieveResponse =
    environmentsIntegrationsClickupWorkspacesRetrieveResponseSuccess

export const getEnvironmentsIntegrationsClickupWorkspacesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/clickup_workspaces/`
}

export const environmentsIntegrationsClickupWorkspacesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsClickupWorkspacesRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsClickupWorkspacesRetrieveResponse>(
        getEnvironmentsIntegrationsClickupWorkspacesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsEmailVerifyCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsEmailVerifyCreateResponseSuccess =
    environmentsIntegrationsEmailVerifyCreateResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsEmailVerifyCreateResponse = environmentsIntegrationsEmailVerifyCreateResponseSuccess

export const getEnvironmentsIntegrationsEmailVerifyCreateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/email/verify/`
}

export const environmentsIntegrationsEmailVerifyCreate = async (
    projectId: string,
    id: number,
    integrationApi: NonReadonly<IntegrationApi>,
    options?: RequestInit
): Promise<environmentsIntegrationsEmailVerifyCreateResponse> => {
    return apiMutator<environmentsIntegrationsEmailVerifyCreateResponse>(
        getEnvironmentsIntegrationsEmailVerifyCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(integrationApi),
        }
    )
}

export type environmentsIntegrationsGithubReposRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsGithubReposRetrieveResponseSuccess =
    environmentsIntegrationsGithubReposRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsGithubReposRetrieveResponse =
    environmentsIntegrationsGithubReposRetrieveResponseSuccess

export const getEnvironmentsIntegrationsGithubReposRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/github_repos/`
}

export const environmentsIntegrationsGithubReposRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsGithubReposRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsGithubReposRetrieveResponse>(
        getEnvironmentsIntegrationsGithubReposRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsGoogleAccessibleAccountsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsGoogleAccessibleAccountsRetrieveResponseSuccess =
    environmentsIntegrationsGoogleAccessibleAccountsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsGoogleAccessibleAccountsRetrieveResponse =
    environmentsIntegrationsGoogleAccessibleAccountsRetrieveResponseSuccess

export const getEnvironmentsIntegrationsGoogleAccessibleAccountsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/google_accessible_accounts/`
}

export const environmentsIntegrationsGoogleAccessibleAccountsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsGoogleAccessibleAccountsRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsGoogleAccessibleAccountsRetrieveResponse>(
        getEnvironmentsIntegrationsGoogleAccessibleAccountsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsGoogleConversionActionsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsGoogleConversionActionsRetrieveResponseSuccess =
    environmentsIntegrationsGoogleConversionActionsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsGoogleConversionActionsRetrieveResponse =
    environmentsIntegrationsGoogleConversionActionsRetrieveResponseSuccess

export const getEnvironmentsIntegrationsGoogleConversionActionsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/google_conversion_actions/`
}

export const environmentsIntegrationsGoogleConversionActionsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsGoogleConversionActionsRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsGoogleConversionActionsRetrieveResponse>(
        getEnvironmentsIntegrationsGoogleConversionActionsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsJiraRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsJiraRetrieveResponseSuccess = environmentsIntegrationsJiraRetrieveResponse200 & {
    headers: Headers
}
export type environmentsIntegrationsJiraRetrieveResponse = environmentsIntegrationsJiraRetrieveResponseSuccess

export const getEnvironmentsIntegrationsJiraRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/jira_projects/`
}

export const environmentsIntegrationsJiraRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsJiraRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsJiraRetrieveResponse>(
        getEnvironmentsIntegrationsJiraRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsLinearTeamsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsLinearTeamsRetrieveResponseSuccess =
    environmentsIntegrationsLinearTeamsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsLinearTeamsRetrieveResponse =
    environmentsIntegrationsLinearTeamsRetrieveResponseSuccess

export const getEnvironmentsIntegrationsLinearTeamsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/linear_teams/`
}

export const environmentsIntegrationsLinearTeamsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsLinearTeamsRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsLinearTeamsRetrieveResponse>(
        getEnvironmentsIntegrationsLinearTeamsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsLinkedinAdsAccountsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsLinkedinAdsAccountsRetrieveResponseSuccess =
    environmentsIntegrationsLinkedinAdsAccountsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsLinkedinAdsAccountsRetrieveResponse =
    environmentsIntegrationsLinkedinAdsAccountsRetrieveResponseSuccess

export const getEnvironmentsIntegrationsLinkedinAdsAccountsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/linkedin_ads_accounts/`
}

export const environmentsIntegrationsLinkedinAdsAccountsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsLinkedinAdsAccountsRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsLinkedinAdsAccountsRetrieveResponse>(
        getEnvironmentsIntegrationsLinkedinAdsAccountsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponseSuccess =
    environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponse =
    environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponseSuccess

export const getEnvironmentsIntegrationsLinkedinAdsConversionRulesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/linkedin_ads_conversion_rules/`
}

export const environmentsIntegrationsLinkedinAdsConversionRulesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsLinkedinAdsConversionRulesRetrieveResponse>(
        getEnvironmentsIntegrationsLinkedinAdsConversionRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsTwilioPhoneNumbersRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsTwilioPhoneNumbersRetrieveResponseSuccess =
    environmentsIntegrationsTwilioPhoneNumbersRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsTwilioPhoneNumbersRetrieveResponse =
    environmentsIntegrationsTwilioPhoneNumbersRetrieveResponseSuccess

export const getEnvironmentsIntegrationsTwilioPhoneNumbersRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/twilio_phone_numbers/`
}

export const environmentsIntegrationsTwilioPhoneNumbersRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsIntegrationsTwilioPhoneNumbersRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsTwilioPhoneNumbersRetrieveResponse>(
        getEnvironmentsIntegrationsTwilioPhoneNumbersRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsIntegrationsAuthorizeRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsIntegrationsAuthorizeRetrieveResponseSuccess =
    environmentsIntegrationsAuthorizeRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsIntegrationsAuthorizeRetrieveResponse = environmentsIntegrationsAuthorizeRetrieveResponseSuccess

export const getEnvironmentsIntegrationsAuthorizeRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/integrations/authorize/`
}

export const environmentsIntegrationsAuthorizeRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsIntegrationsAuthorizeRetrieveResponse> => {
    return apiMutator<environmentsIntegrationsAuthorizeRetrieveResponse>(
        getEnvironmentsIntegrationsAuthorizeRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsSessionRecordingsSharingListResponse200 = {
    data: SharingConfigurationApi[]
    status: 200
}

export type environmentsSessionRecordingsSharingListResponseSuccess =
    environmentsSessionRecordingsSharingListResponse200 & {
        headers: Headers
    }
export type environmentsSessionRecordingsSharingListResponse = environmentsSessionRecordingsSharingListResponseSuccess

export const getEnvironmentsSessionRecordingsSharingListUrl = (projectId: string, recordingId: string) => {
    return `/api/environments/${projectId}/session_recordings/${recordingId}/sharing/`
}

export const environmentsSessionRecordingsSharingList = async (
    projectId: string,
    recordingId: string,
    options?: RequestInit
): Promise<environmentsSessionRecordingsSharingListResponse> => {
    return apiMutator<environmentsSessionRecordingsSharingListResponse>(
        getEnvironmentsSessionRecordingsSharingListUrl(projectId, recordingId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create a new password for the sharing configuration.
 */
export type environmentsSessionRecordingsSharingPasswordsCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type environmentsSessionRecordingsSharingPasswordsCreateResponseSuccess =
    environmentsSessionRecordingsSharingPasswordsCreateResponse200 & {
        headers: Headers
    }
export type environmentsSessionRecordingsSharingPasswordsCreateResponse =
    environmentsSessionRecordingsSharingPasswordsCreateResponseSuccess

export const getEnvironmentsSessionRecordingsSharingPasswordsCreateUrl = (projectId: string, recordingId: string) => {
    return `/api/environments/${projectId}/session_recordings/${recordingId}/sharing/passwords/`
}

export const environmentsSessionRecordingsSharingPasswordsCreate = async (
    projectId: string,
    recordingId: string,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<environmentsSessionRecordingsSharingPasswordsCreateResponse> => {
    return apiMutator<environmentsSessionRecordingsSharingPasswordsCreateResponse>(
        getEnvironmentsSessionRecordingsSharingPasswordsCreateUrl(projectId, recordingId),
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
export type environmentsSessionRecordingsSharingPasswordsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsSessionRecordingsSharingPasswordsDestroyResponseSuccess =
    environmentsSessionRecordingsSharingPasswordsDestroyResponse204 & {
        headers: Headers
    }
export type environmentsSessionRecordingsSharingPasswordsDestroyResponse =
    environmentsSessionRecordingsSharingPasswordsDestroyResponseSuccess

export const getEnvironmentsSessionRecordingsSharingPasswordsDestroyUrl = (
    projectId: string,
    recordingId: string,
    passwordId: string
) => {
    return `/api/environments/${projectId}/session_recordings/${recordingId}/sharing/passwords/${passwordId}/`
}

export const environmentsSessionRecordingsSharingPasswordsDestroy = async (
    projectId: string,
    recordingId: string,
    passwordId: string,
    options?: RequestInit
): Promise<environmentsSessionRecordingsSharingPasswordsDestroyResponse> => {
    return apiMutator<environmentsSessionRecordingsSharingPasswordsDestroyResponse>(
        getEnvironmentsSessionRecordingsSharingPasswordsDestroyUrl(projectId, recordingId, passwordId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsSessionRecordingsSharingRefreshCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type environmentsSessionRecordingsSharingRefreshCreateResponseSuccess =
    environmentsSessionRecordingsSharingRefreshCreateResponse200 & {
        headers: Headers
    }
export type environmentsSessionRecordingsSharingRefreshCreateResponse =
    environmentsSessionRecordingsSharingRefreshCreateResponseSuccess

export const getEnvironmentsSessionRecordingsSharingRefreshCreateUrl = (projectId: string, recordingId: string) => {
    return `/api/environments/${projectId}/session_recordings/${recordingId}/sharing/refresh/`
}

export const environmentsSessionRecordingsSharingRefreshCreate = async (
    projectId: string,
    recordingId: string,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<environmentsSessionRecordingsSharingRefreshCreateResponse> => {
    return apiMutator<environmentsSessionRecordingsSharingRefreshCreateResponse>(
        getEnvironmentsSessionRecordingsSharingRefreshCreateUrl(projectId, recordingId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sharingConfigurationApi),
        }
    )
}

export type environmentsSubscriptionsListResponse200 = {
    data: PaginatedSubscriptionListApi
    status: 200
}

export type environmentsSubscriptionsListResponseSuccess = environmentsSubscriptionsListResponse200 & {
    headers: Headers
}
export type environmentsSubscriptionsListResponse = environmentsSubscriptionsListResponseSuccess

export const getEnvironmentsSubscriptionsListUrl = (
    projectId: string,
    params?: EnvironmentsSubscriptionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/subscriptions/?${stringifiedParams}`
        : `/api/environments/${projectId}/subscriptions/`
}

export const environmentsSubscriptionsList = async (
    projectId: string,
    params?: EnvironmentsSubscriptionsListParams,
    options?: RequestInit
): Promise<environmentsSubscriptionsListResponse> => {
    return apiMutator<environmentsSubscriptionsListResponse>(getEnvironmentsSubscriptionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsSubscriptionsCreateResponse201 = {
    data: SubscriptionApi
    status: 201
}

export type environmentsSubscriptionsCreateResponseSuccess = environmentsSubscriptionsCreateResponse201 & {
    headers: Headers
}
export type environmentsSubscriptionsCreateResponse = environmentsSubscriptionsCreateResponseSuccess

export const getEnvironmentsSubscriptionsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/subscriptions/`
}

export const environmentsSubscriptionsCreate = async (
    projectId: string,
    subscriptionApi: NonReadonly<SubscriptionApi>,
    options?: RequestInit
): Promise<environmentsSubscriptionsCreateResponse> => {
    return apiMutator<environmentsSubscriptionsCreateResponse>(getEnvironmentsSubscriptionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionApi),
    })
}

export type environmentsSubscriptionsRetrieveResponse200 = {
    data: SubscriptionApi
    status: 200
}

export type environmentsSubscriptionsRetrieveResponseSuccess = environmentsSubscriptionsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsSubscriptionsRetrieveResponse = environmentsSubscriptionsRetrieveResponseSuccess

export const getEnvironmentsSubscriptionsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/subscriptions/${id}/`
}

export const environmentsSubscriptionsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsSubscriptionsRetrieveResponse> => {
    return apiMutator<environmentsSubscriptionsRetrieveResponse>(
        getEnvironmentsSubscriptionsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsSubscriptionsUpdateResponse200 = {
    data: SubscriptionApi
    status: 200
}

export type environmentsSubscriptionsUpdateResponseSuccess = environmentsSubscriptionsUpdateResponse200 & {
    headers: Headers
}
export type environmentsSubscriptionsUpdateResponse = environmentsSubscriptionsUpdateResponseSuccess

export const getEnvironmentsSubscriptionsUpdateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/subscriptions/${id}/`
}

export const environmentsSubscriptionsUpdate = async (
    projectId: string,
    id: number,
    subscriptionApi: NonReadonly<SubscriptionApi>,
    options?: RequestInit
): Promise<environmentsSubscriptionsUpdateResponse> => {
    return apiMutator<environmentsSubscriptionsUpdateResponse>(getEnvironmentsSubscriptionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionApi),
    })
}

export type environmentsSubscriptionsPartialUpdateResponse200 = {
    data: SubscriptionApi
    status: 200
}

export type environmentsSubscriptionsPartialUpdateResponseSuccess =
    environmentsSubscriptionsPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsSubscriptionsPartialUpdateResponse = environmentsSubscriptionsPartialUpdateResponseSuccess

export const getEnvironmentsSubscriptionsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/subscriptions/${id}/`
}

export const environmentsSubscriptionsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedSubscriptionApi: NonReadonly<PatchedSubscriptionApi>,
    options?: RequestInit
): Promise<environmentsSubscriptionsPartialUpdateResponse> => {
    return apiMutator<environmentsSubscriptionsPartialUpdateResponse>(
        getEnvironmentsSubscriptionsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedSubscriptionApi),
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type environmentsSubscriptionsDestroyResponse405 = {
    data: void
    status: 405
}
export type environmentsSubscriptionsDestroyResponseError = environmentsSubscriptionsDestroyResponse405 & {
    headers: Headers
}

export type environmentsSubscriptionsDestroyResponse = environmentsSubscriptionsDestroyResponseError

export const getEnvironmentsSubscriptionsDestroyUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/subscriptions/${id}/`
}

export const environmentsSubscriptionsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsSubscriptionsDestroyResponse> => {
    return apiMutator<environmentsSubscriptionsDestroyResponse>(getEnvironmentsSubscriptionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type domainsListResponse200 = {
    data: PaginatedOrganizationDomainListApi
    status: 200
}

export type domainsListResponseSuccess = domainsListResponse200 & {
    headers: Headers
}
export type domainsListResponse = domainsListResponseSuccess

export const getDomainsListUrl = (organizationId: string, params?: DomainsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/domains/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/domains/`
}

export const domainsList = async (
    organizationId: string,
    params?: DomainsListParams,
    options?: RequestInit
): Promise<domainsListResponse> => {
    return apiMutator<domainsListResponse>(getDomainsListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export type domainsCreateResponse201 = {
    data: OrganizationDomainApi
    status: 201
}

export type domainsCreateResponseSuccess = domainsCreateResponse201 & {
    headers: Headers
}
export type domainsCreateResponse = domainsCreateResponseSuccess

export const getDomainsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/domains/`
}

export const domainsCreate = async (
    organizationId: string,
    organizationDomainApi: NonReadonly<OrganizationDomainApi>,
    options?: RequestInit
): Promise<domainsCreateResponse> => {
    return apiMutator<domainsCreateResponse>(getDomainsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationDomainApi),
    })
}

export type domainsRetrieveResponse200 = {
    data: OrganizationDomainApi
    status: 200
}

export type domainsRetrieveResponseSuccess = domainsRetrieveResponse200 & {
    headers: Headers
}
export type domainsRetrieveResponse = domainsRetrieveResponseSuccess

export const getDomainsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/`
}

export const domainsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<domainsRetrieveResponse> => {
    return apiMutator<domainsRetrieveResponse>(getDomainsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export type domainsUpdateResponse200 = {
    data: OrganizationDomainApi
    status: 200
}

export type domainsUpdateResponseSuccess = domainsUpdateResponse200 & {
    headers: Headers
}
export type domainsUpdateResponse = domainsUpdateResponseSuccess

export const getDomainsUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/`
}

export const domainsUpdate = async (
    organizationId: string,
    id: string,
    organizationDomainApi: NonReadonly<OrganizationDomainApi>,
    options?: RequestInit
): Promise<domainsUpdateResponse> => {
    return apiMutator<domainsUpdateResponse>(getDomainsUpdateUrl(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationDomainApi),
    })
}

export type domainsPartialUpdateResponse200 = {
    data: OrganizationDomainApi
    status: 200
}

export type domainsPartialUpdateResponseSuccess = domainsPartialUpdateResponse200 & {
    headers: Headers
}
export type domainsPartialUpdateResponse = domainsPartialUpdateResponseSuccess

export const getDomainsPartialUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/`
}

export const domainsPartialUpdate = async (
    organizationId: string,
    id: string,
    patchedOrganizationDomainApi: NonReadonly<PatchedOrganizationDomainApi>,
    options?: RequestInit
): Promise<domainsPartialUpdateResponse> => {
    return apiMutator<domainsPartialUpdateResponse>(getDomainsPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedOrganizationDomainApi),
    })
}

export type domainsDestroyResponse204 = {
    data: void
    status: 204
}

export type domainsDestroyResponseSuccess = domainsDestroyResponse204 & {
    headers: Headers
}
export type domainsDestroyResponse = domainsDestroyResponseSuccess

export const getDomainsDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/`
}

export const domainsDestroy = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<domainsDestroyResponse> => {
    return apiMutator<domainsDestroyResponse>(getDomainsDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Regenerate SCIM bearer token.
 */
export type domainsScimTokenCreateResponse200 = {
    data: void
    status: 200
}

export type domainsScimTokenCreateResponseSuccess = domainsScimTokenCreateResponse200 & {
    headers: Headers
}
export type domainsScimTokenCreateResponse = domainsScimTokenCreateResponseSuccess

export const getDomainsScimTokenCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/scim/token/`
}

export const domainsScimTokenCreate = async (
    organizationId: string,
    id: string,
    organizationDomainApi: NonReadonly<OrganizationDomainApi>,
    options?: RequestInit
): Promise<domainsScimTokenCreateResponse> => {
    return apiMutator<domainsScimTokenCreateResponse>(getDomainsScimTokenCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationDomainApi),
    })
}

export type domainsVerifyCreateResponse200 = {
    data: void
    status: 200
}

export type domainsVerifyCreateResponseSuccess = domainsVerifyCreateResponse200 & {
    headers: Headers
}
export type domainsVerifyCreateResponse = domainsVerifyCreateResponseSuccess

export const getDomainsVerifyCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/verify/`
}

export const domainsVerifyCreate = async (
    organizationId: string,
    id: string,
    organizationDomainApi: NonReadonly<OrganizationDomainApi>,
    options?: RequestInit
): Promise<domainsVerifyCreateResponse> => {
    return apiMutator<domainsVerifyCreateResponse>(getDomainsVerifyCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationDomainApi),
    })
}

export type invitesListResponse200 = {
    data: PaginatedOrganizationInviteListApi
    status: 200
}

export type invitesListResponseSuccess = invitesListResponse200 & {
    headers: Headers
}
export type invitesListResponse = invitesListResponseSuccess

export const getInvitesListUrl = (organizationId: string, params?: InvitesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/invites/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/invites/`
}

export const invitesList = async (
    organizationId: string,
    params?: InvitesListParams,
    options?: RequestInit
): Promise<invitesListResponse> => {
    return apiMutator<invitesListResponse>(getInvitesListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export type invitesCreateResponse201 = {
    data: OrganizationInviteApi
    status: 201
}

export type invitesCreateResponseSuccess = invitesCreateResponse201 & {
    headers: Headers
}
export type invitesCreateResponse = invitesCreateResponseSuccess

export const getInvitesCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/invites/`
}

export const invitesCreate = async (
    organizationId: string,
    organizationInviteApi: NonReadonly<OrganizationInviteApi>,
    options?: RequestInit
): Promise<invitesCreateResponse> => {
    return apiMutator<invitesCreateResponse>(getInvitesCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationInviteApi),
    })
}

export type invitesDestroyResponse204 = {
    data: void
    status: 204
}

export type invitesDestroyResponseSuccess = invitesDestroyResponse204 & {
    headers: Headers
}
export type invitesDestroyResponse = invitesDestroyResponseSuccess

export const getInvitesDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/invites/${id}/`
}

export const invitesDestroy = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<invitesDestroyResponse> => {
    return apiMutator<invitesDestroyResponse>(getInvitesDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type invitesBulkCreateResponse200 = {
    data: void
    status: 200
}

export type invitesBulkCreateResponseSuccess = invitesBulkCreateResponse200 & {
    headers: Headers
}
export type invitesBulkCreateResponse = invitesBulkCreateResponseSuccess

export const getInvitesBulkCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/invites/bulk/`
}

export const invitesBulkCreate = async (
    organizationId: string,
    organizationInviteApi: NonReadonly<OrganizationInviteApi>,
    options?: RequestInit
): Promise<invitesBulkCreateResponse> => {
    return apiMutator<invitesBulkCreateResponse>(getInvitesBulkCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationInviteApi),
    })
}

export type membersListResponse200 = {
    data: PaginatedOrganizationMemberListApi
    status: 200
}

export type membersListResponseSuccess = membersListResponse200 & {
    headers: Headers
}
export type membersListResponse = membersListResponseSuccess

export const getMembersListUrl = (organizationId: string, params?: MembersListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/members/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/members/`
}

export const membersList = async (
    organizationId: string,
    params?: MembersListParams,
    options?: RequestInit
): Promise<membersListResponse> => {
    return apiMutator<membersListResponse>(getMembersListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export type membersUpdateResponse200 = {
    data: OrganizationMemberApi
    status: 200
}

export type membersUpdateResponseSuccess = membersUpdateResponse200 & {
    headers: Headers
}
export type membersUpdateResponse = membersUpdateResponseSuccess

export const getMembersUpdateUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/`
}

export const membersUpdate = async (
    organizationId: string,
    userUuid: string,
    organizationMemberApi: NonReadonly<OrganizationMemberApi>,
    options?: RequestInit
): Promise<membersUpdateResponse> => {
    return apiMutator<membersUpdateResponse>(getMembersUpdateUrl(organizationId, userUuid), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationMemberApi),
    })
}

export type membersPartialUpdateResponse200 = {
    data: OrganizationMemberApi
    status: 200
}

export type membersPartialUpdateResponseSuccess = membersPartialUpdateResponse200 & {
    headers: Headers
}
export type membersPartialUpdateResponse = membersPartialUpdateResponseSuccess

export const getMembersPartialUpdateUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/`
}

export const membersPartialUpdate = async (
    organizationId: string,
    userUuid: string,
    patchedOrganizationMemberApi: NonReadonly<PatchedOrganizationMemberApi>,
    options?: RequestInit
): Promise<membersPartialUpdateResponse> => {
    return apiMutator<membersPartialUpdateResponse>(getMembersPartialUpdateUrl(organizationId, userUuid), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedOrganizationMemberApi),
    })
}

export type membersDestroyResponse204 = {
    data: void
    status: 204
}

export type membersDestroyResponseSuccess = membersDestroyResponse204 & {
    headers: Headers
}
export type membersDestroyResponse = membersDestroyResponseSuccess

export const getMembersDestroyUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/`
}

export const membersDestroy = async (
    organizationId: string,
    userUuid: string,
    options?: RequestInit
): Promise<membersDestroyResponse> => {
    return apiMutator<membersDestroyResponse>(getMembersDestroyUrl(organizationId, userUuid), {
        ...options,
        method: 'DELETE',
    })
}

export type membersScopedApiKeysRetrieveResponse200 = {
    data: OrganizationMemberApi
    status: 200
}

export type membersScopedApiKeysRetrieveResponseSuccess = membersScopedApiKeysRetrieveResponse200 & {
    headers: Headers
}
export type membersScopedApiKeysRetrieveResponse = membersScopedApiKeysRetrieveResponseSuccess

export const getMembersScopedApiKeysRetrieveUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/scoped_api_keys/`
}

export const membersScopedApiKeysRetrieve = async (
    organizationId: string,
    userUuid: string,
    options?: RequestInit
): Promise<membersScopedApiKeysRetrieveResponse> => {
    return apiMutator<membersScopedApiKeysRetrieveResponse>(
        getMembersScopedApiKeysRetrieveUrl(organizationId, userUuid),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Projects for the current organization.
 */
export type list2Response200 = {
    data: PaginatedProjectBackwardCompatBasicListApi
    status: 200
}

export type list2ResponseSuccess = list2Response200 & {
    headers: Headers
}
export type list2Response = list2ResponseSuccess

export const getList2Url = (organizationId: string, params?: List2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/projects/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/projects/`
}

export const list2 = async (
    organizationId: string,
    params?: List2Params,
    options?: RequestInit
): Promise<list2Response> => {
    return apiMutator<list2Response>(getList2Url(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Projects for the current organization.
 */
export type create2Response201 = {
    data: ProjectBackwardCompatApi
    status: 201
}

export type create2ResponseSuccess = create2Response201 & {
    headers: Headers
}
export type create2Response = create2ResponseSuccess

export const getCreate2Url = (organizationId: string) => {
    return `/api/organizations/${organizationId}/projects/`
}

export const create2 = async (
    organizationId: string,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<create2Response> => {
    return apiMutator<create2Response>(getCreate2Url(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export type retrieve2Response200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type retrieve2ResponseSuccess = retrieve2Response200 & {
    headers: Headers
}
export type retrieve2Response = retrieve2ResponseSuccess

export const getRetrieve2Url = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

export const retrieve2 = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<retrieve2Response> => {
    return apiMutator<retrieve2Response>(getRetrieve2Url(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Projects for the current organization.
 */
export type update2Response200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type update2ResponseSuccess = update2Response200 & {
    headers: Headers
}
export type update2Response = update2ResponseSuccess

export const getUpdate2Url = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

export const update2 = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<update2Response> => {
    return apiMutator<update2Response>(getUpdate2Url(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export type partialUpdate2Response200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type partialUpdate2ResponseSuccess = partialUpdate2Response200 & {
    headers: Headers
}
export type partialUpdate2Response = partialUpdate2ResponseSuccess

export const getPartialUpdate2Url = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

export const partialUpdate2 = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<partialUpdate2Response> => {
    return apiMutator<partialUpdate2Response>(getPartialUpdate2Url(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export type destroy2Response204 = {
    data: void
    status: 204
}

export type destroy2ResponseSuccess = destroy2Response204 & {
    headers: Headers
}
export type destroy2Response = destroy2ResponseSuccess

export const getDestroy2Url = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

export const destroy2 = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<destroy2Response> => {
    return apiMutator<destroy2Response>(getDestroy2Url(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Projects for the current organization.
 */
export type activityRetrieveResponse200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type activityRetrieveResponseSuccess = activityRetrieveResponse200 & {
    headers: Headers
}
export type activityRetrieveResponse = activityRetrieveResponseSuccess

export const getActivityRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/activity/`
}

export const activityRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<activityRetrieveResponse> => {
    return apiMutator<activityRetrieveResponse>(getActivityRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Projects for the current organization.
 */
export type addProductIntentPartialUpdateResponse200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type addProductIntentPartialUpdateResponseSuccess = addProductIntentPartialUpdateResponse200 & {
    headers: Headers
}
export type addProductIntentPartialUpdateResponse = addProductIntentPartialUpdateResponseSuccess

export const getAddProductIntentPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/add_product_intent/`
}

export const addProductIntentPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<addProductIntentPartialUpdateResponse> => {
    return apiMutator<addProductIntentPartialUpdateResponse>(getAddProductIntentPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export type changeOrganizationCreateResponse200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type changeOrganizationCreateResponseSuccess = changeOrganizationCreateResponse200 & {
    headers: Headers
}
export type changeOrganizationCreateResponse = changeOrganizationCreateResponseSuccess

export const getChangeOrganizationCreateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/change_organization/`
}

export const changeOrganizationCreate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<changeOrganizationCreateResponse> => {
    return apiMutator<changeOrganizationCreateResponse>(getChangeOrganizationCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export type completeProductOnboardingPartialUpdateResponse200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type completeProductOnboardingPartialUpdateResponseSuccess =
    completeProductOnboardingPartialUpdateResponse200 & {
        headers: Headers
    }
export type completeProductOnboardingPartialUpdateResponse = completeProductOnboardingPartialUpdateResponseSuccess

export const getCompleteProductOnboardingPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/complete_product_onboarding/`
}

export const completeProductOnboardingPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<completeProductOnboardingPartialUpdateResponse> => {
    return apiMutator<completeProductOnboardingPartialUpdateResponse>(
        getCompleteProductOnboardingPartialUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedProjectBackwardCompatApi),
        }
    )
}

/**
 * Projects for the current organization.
 */
export type deleteSecretTokenBackupPartialUpdateResponse200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type deleteSecretTokenBackupPartialUpdateResponseSuccess = deleteSecretTokenBackupPartialUpdateResponse200 & {
    headers: Headers
}
export type deleteSecretTokenBackupPartialUpdateResponse = deleteSecretTokenBackupPartialUpdateResponseSuccess

export const getDeleteSecretTokenBackupPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/delete_secret_token_backup/`
}

export const deleteSecretTokenBackupPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<deleteSecretTokenBackupPartialUpdateResponse> => {
    return apiMutator<deleteSecretTokenBackupPartialUpdateResponse>(
        getDeleteSecretTokenBackupPartialUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedProjectBackwardCompatApi),
        }
    )
}

/**
 * Projects for the current organization.
 */
export type generateConversationsPublicTokenCreateResponse200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type generateConversationsPublicTokenCreateResponseSuccess =
    generateConversationsPublicTokenCreateResponse200 & {
        headers: Headers
    }
export type generateConversationsPublicTokenCreateResponse = generateConversationsPublicTokenCreateResponseSuccess

export const getGenerateConversationsPublicTokenCreateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/generate_conversations_public_token/`
}

export const generateConversationsPublicTokenCreate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<generateConversationsPublicTokenCreateResponse> => {
    return apiMutator<generateConversationsPublicTokenCreateResponse>(
        getGenerateConversationsPublicTokenCreateUrl(organizationId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(projectBackwardCompatApi),
        }
    )
}

/**
 * Projects for the current organization.
 */
export type isGeneratingDemoDataRetrieveResponse200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type isGeneratingDemoDataRetrieveResponseSuccess = isGeneratingDemoDataRetrieveResponse200 & {
    headers: Headers
}
export type isGeneratingDemoDataRetrieveResponse = isGeneratingDemoDataRetrieveResponseSuccess

export const getIsGeneratingDemoDataRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/is_generating_demo_data/`
}

export const isGeneratingDemoDataRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<isGeneratingDemoDataRetrieveResponse> => {
    return apiMutator<isGeneratingDemoDataRetrieveResponse>(getIsGeneratingDemoDataRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Projects for the current organization.
 */
export type resetTokenPartialUpdateResponse200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type resetTokenPartialUpdateResponseSuccess = resetTokenPartialUpdateResponse200 & {
    headers: Headers
}
export type resetTokenPartialUpdateResponse = resetTokenPartialUpdateResponseSuccess

export const getResetTokenPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/reset_token/`
}

export const resetTokenPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<resetTokenPartialUpdateResponse> => {
    return apiMutator<resetTokenPartialUpdateResponse>(getResetTokenPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export type rotateSecretTokenPartialUpdateResponse200 = {
    data: ProjectBackwardCompatApi
    status: 200
}

export type rotateSecretTokenPartialUpdateResponseSuccess = rotateSecretTokenPartialUpdateResponse200 & {
    headers: Headers
}
export type rotateSecretTokenPartialUpdateResponse = rotateSecretTokenPartialUpdateResponseSuccess

export const getRotateSecretTokenPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/rotate_secret_token/`
}

export const rotateSecretTokenPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<rotateSecretTokenPartialUpdateResponse> => {
    return apiMutator<rotateSecretTokenPartialUpdateResponse>(
        getRotateSecretTokenPartialUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedProjectBackwardCompatApi),
        }
    )
}

export type rolesListResponse200 = {
    data: PaginatedRoleListApi
    status: 200
}

export type rolesListResponseSuccess = rolesListResponse200 & {
    headers: Headers
}
export type rolesListResponse = rolesListResponseSuccess

export const getRolesListUrl = (organizationId: string, params?: RolesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/roles/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/roles/`
}

export const rolesList = async (
    organizationId: string,
    params?: RolesListParams,
    options?: RequestInit
): Promise<rolesListResponse> => {
    return apiMutator<rolesListResponse>(getRolesListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export type rolesCreateResponse201 = {
    data: RoleApi
    status: 201
}

export type rolesCreateResponseSuccess = rolesCreateResponse201 & {
    headers: Headers
}
export type rolesCreateResponse = rolesCreateResponseSuccess

export const getRolesCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/roles/`
}

export const rolesCreate = async (
    organizationId: string,
    roleApi: NonReadonly<RoleApi>,
    options?: RequestInit
): Promise<rolesCreateResponse> => {
    return apiMutator<rolesCreateResponse>(getRolesCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(roleApi),
    })
}

export type rolesRetrieveResponse200 = {
    data: RoleApi
    status: 200
}

export type rolesRetrieveResponseSuccess = rolesRetrieveResponse200 & {
    headers: Headers
}
export type rolesRetrieveResponse = rolesRetrieveResponseSuccess

export const getRolesRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/roles/${id}/`
}

export const rolesRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<rolesRetrieveResponse> => {
    return apiMutator<rolesRetrieveResponse>(getRolesRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export type rolesUpdateResponse200 = {
    data: RoleApi
    status: 200
}

export type rolesUpdateResponseSuccess = rolesUpdateResponse200 & {
    headers: Headers
}
export type rolesUpdateResponse = rolesUpdateResponseSuccess

export const getRolesUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/roles/${id}/`
}

export const rolesUpdate = async (
    organizationId: string,
    id: string,
    roleApi: NonReadonly<RoleApi>,
    options?: RequestInit
): Promise<rolesUpdateResponse> => {
    return apiMutator<rolesUpdateResponse>(getRolesUpdateUrl(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(roleApi),
    })
}

export type rolesPartialUpdateResponse200 = {
    data: RoleApi
    status: 200
}

export type rolesPartialUpdateResponseSuccess = rolesPartialUpdateResponse200 & {
    headers: Headers
}
export type rolesPartialUpdateResponse = rolesPartialUpdateResponseSuccess

export const getRolesPartialUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/roles/${id}/`
}

export const rolesPartialUpdate = async (
    organizationId: string,
    id: string,
    patchedRoleApi: NonReadonly<PatchedRoleApi>,
    options?: RequestInit
): Promise<rolesPartialUpdateResponse> => {
    return apiMutator<rolesPartialUpdateResponse>(getRolesPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedRoleApi),
    })
}

export type rolesDestroyResponse204 = {
    data: void
    status: 204
}

export type rolesDestroyResponseSuccess = rolesDestroyResponse204 & {
    headers: Headers
}
export type rolesDestroyResponse = rolesDestroyResponseSuccess

export const getRolesDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/roles/${id}/`
}

export const rolesDestroy = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<rolesDestroyResponse> => {
    return apiMutator<rolesDestroyResponse>(getRolesDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export type annotationsListResponse200 = {
    data: PaginatedAnnotationListApi
    status: 200
}

export type annotationsListResponseSuccess = annotationsListResponse200 & {
    headers: Headers
}
export type annotationsListResponse = annotationsListResponseSuccess

export const getAnnotationsListUrl = (projectId: string, params?: AnnotationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/annotations/?${stringifiedParams}`
        : `/api/projects/${projectId}/annotations/`
}

export const annotationsList = async (
    projectId: string,
    params?: AnnotationsListParams,
    options?: RequestInit
): Promise<annotationsListResponse> => {
    return apiMutator<annotationsListResponse>(getAnnotationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export type annotationsCreateResponse201 = {
    data: AnnotationApi
    status: 201
}

export type annotationsCreateResponseSuccess = annotationsCreateResponse201 & {
    headers: Headers
}
export type annotationsCreateResponse = annotationsCreateResponseSuccess

export const getAnnotationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/annotations/`
}

export const annotationsCreate = async (
    projectId: string,
    annotationApi: NonReadonly<AnnotationApi>,
    options?: RequestInit
): Promise<annotationsCreateResponse> => {
    return apiMutator<annotationsCreateResponse>(getAnnotationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(annotationApi),
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export type annotationsRetrieveResponse200 = {
    data: AnnotationApi
    status: 200
}

export type annotationsRetrieveResponseSuccess = annotationsRetrieveResponse200 & {
    headers: Headers
}
export type annotationsRetrieveResponse = annotationsRetrieveResponseSuccess

export const getAnnotationsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<annotationsRetrieveResponse> => {
    return apiMutator<annotationsRetrieveResponse>(getAnnotationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export type annotationsUpdateResponse200 = {
    data: AnnotationApi
    status: 200
}

export type annotationsUpdateResponseSuccess = annotationsUpdateResponse200 & {
    headers: Headers
}
export type annotationsUpdateResponse = annotationsUpdateResponseSuccess

export const getAnnotationsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsUpdate = async (
    projectId: string,
    id: number,
    annotationApi: NonReadonly<AnnotationApi>,
    options?: RequestInit
): Promise<annotationsUpdateResponse> => {
    return apiMutator<annotationsUpdateResponse>(getAnnotationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(annotationApi),
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export type annotationsPartialUpdateResponse200 = {
    data: AnnotationApi
    status: 200
}

export type annotationsPartialUpdateResponseSuccess = annotationsPartialUpdateResponse200 & {
    headers: Headers
}
export type annotationsPartialUpdateResponse = annotationsPartialUpdateResponseSuccess

export const getAnnotationsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedAnnotationApi: NonReadonly<PatchedAnnotationApi>,
    options?: RequestInit
): Promise<annotationsPartialUpdateResponse> => {
    return apiMutator<annotationsPartialUpdateResponse>(getAnnotationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAnnotationApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type annotationsDestroyResponse405 = {
    data: void
    status: 405
}
export type annotationsDestroyResponseError = annotationsDestroyResponse405 & {
    headers: Headers
}

export type annotationsDestroyResponse = annotationsDestroyResponseError

export const getAnnotationsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<annotationsDestroyResponse> => {
    return apiMutator<annotationsDestroyResponse>(getAnnotationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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

export type commentsListResponse200 = {
    data: PaginatedCommentListApi
    status: 200
}

export type commentsListResponseSuccess = commentsListResponse200 & {
    headers: Headers
}
export type commentsListResponse = commentsListResponseSuccess

export const getCommentsListUrl = (projectId: string, params?: CommentsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/comments/?${stringifiedParams}`
        : `/api/projects/${projectId}/comments/`
}

export const commentsList = async (
    projectId: string,
    params?: CommentsListParams,
    options?: RequestInit
): Promise<commentsListResponse> => {
    return apiMutator<commentsListResponse>(getCommentsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type commentsCreateResponse201 = {
    data: CommentApi
    status: 201
}

export type commentsCreateResponseSuccess = commentsCreateResponse201 & {
    headers: Headers
}
export type commentsCreateResponse = commentsCreateResponseSuccess

export const getCommentsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/comments/`
}

export const commentsCreate = async (
    projectId: string,
    commentApi: NonReadonly<CommentApi>,
    options?: RequestInit
): Promise<commentsCreateResponse> => {
    return apiMutator<commentsCreateResponse>(getCommentsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(commentApi),
    })
}

export type commentsRetrieveResponse200 = {
    data: CommentApi
    status: 200
}

export type commentsRetrieveResponseSuccess = commentsRetrieveResponse200 & {
    headers: Headers
}
export type commentsRetrieveResponse = commentsRetrieveResponseSuccess

export const getCommentsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<commentsRetrieveResponse> => {
    return apiMutator<commentsRetrieveResponse>(getCommentsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type commentsUpdateResponse200 = {
    data: CommentApi
    status: 200
}

export type commentsUpdateResponseSuccess = commentsUpdateResponse200 & {
    headers: Headers
}
export type commentsUpdateResponse = commentsUpdateResponseSuccess

export const getCommentsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsUpdate = async (
    projectId: string,
    id: string,
    commentApi: NonReadonly<CommentApi>,
    options?: RequestInit
): Promise<commentsUpdateResponse> => {
    return apiMutator<commentsUpdateResponse>(getCommentsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(commentApi),
    })
}

export type commentsPartialUpdateResponse200 = {
    data: CommentApi
    status: 200
}

export type commentsPartialUpdateResponseSuccess = commentsPartialUpdateResponse200 & {
    headers: Headers
}
export type commentsPartialUpdateResponse = commentsPartialUpdateResponseSuccess

export const getCommentsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCommentApi: NonReadonly<PatchedCommentApi>,
    options?: RequestInit
): Promise<commentsPartialUpdateResponse> => {
    return apiMutator<commentsPartialUpdateResponse>(getCommentsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCommentApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type commentsDestroyResponse405 = {
    data: void
    status: 405
}
export type commentsDestroyResponseError = commentsDestroyResponse405 & {
    headers: Headers
}

export type commentsDestroyResponse = commentsDestroyResponseError

export const getCommentsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<commentsDestroyResponse> => {
    return apiMutator<commentsDestroyResponse>(getCommentsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type commentsThreadRetrieveResponse200 = {
    data: void
    status: 200
}

export type commentsThreadRetrieveResponseSuccess = commentsThreadRetrieveResponse200 & {
    headers: Headers
}
export type commentsThreadRetrieveResponse = commentsThreadRetrieveResponseSuccess

export const getCommentsThreadRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/thread/`
}

export const commentsThreadRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<commentsThreadRetrieveResponse> => {
    return apiMutator<commentsThreadRetrieveResponse>(getCommentsThreadRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type commentsCountRetrieveResponse200 = {
    data: void
    status: 200
}

export type commentsCountRetrieveResponseSuccess = commentsCountRetrieveResponse200 & {
    headers: Headers
}
export type commentsCountRetrieveResponse = commentsCountRetrieveResponseSuccess

export const getCommentsCountRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/comments/count/`
}

export const commentsCountRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<commentsCountRetrieveResponse> => {
    return apiMutator<commentsCountRetrieveResponse>(getCommentsCountRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type dashboardTemplatesListResponse200 = {
    data: PaginatedDashboardTemplateListApi
    status: 200
}

export type dashboardTemplatesListResponseSuccess = dashboardTemplatesListResponse200 & {
    headers: Headers
}
export type dashboardTemplatesListResponse = dashboardTemplatesListResponseSuccess

export const getDashboardTemplatesListUrl = (projectId: string, params?: DashboardTemplatesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dashboard_templates/?${stringifiedParams}`
        : `/api/projects/${projectId}/dashboard_templates/`
}

export const dashboardTemplatesList = async (
    projectId: string,
    params?: DashboardTemplatesListParams,
    options?: RequestInit
): Promise<dashboardTemplatesListResponse> => {
    return apiMutator<dashboardTemplatesListResponse>(getDashboardTemplatesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type dashboardTemplatesCreateResponse201 = {
    data: DashboardTemplateApi
    status: 201
}

export type dashboardTemplatesCreateResponseSuccess = dashboardTemplatesCreateResponse201 & {
    headers: Headers
}
export type dashboardTemplatesCreateResponse = dashboardTemplatesCreateResponseSuccess

export const getDashboardTemplatesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/dashboard_templates/`
}

export const dashboardTemplatesCreate = async (
    projectId: string,
    dashboardTemplateApi: NonReadonly<DashboardTemplateApi>,
    options?: RequestInit
): Promise<dashboardTemplatesCreateResponse> => {
    return apiMutator<dashboardTemplatesCreateResponse>(getDashboardTemplatesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardTemplateApi),
    })
}

export type dashboardTemplatesRetrieveResponse200 = {
    data: DashboardTemplateApi
    status: 200
}

export type dashboardTemplatesRetrieveResponseSuccess = dashboardTemplatesRetrieveResponse200 & {
    headers: Headers
}
export type dashboardTemplatesRetrieveResponse = dashboardTemplatesRetrieveResponseSuccess

export const getDashboardTemplatesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

export const dashboardTemplatesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<dashboardTemplatesRetrieveResponse> => {
    return apiMutator<dashboardTemplatesRetrieveResponse>(getDashboardTemplatesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type dashboardTemplatesUpdateResponse200 = {
    data: DashboardTemplateApi
    status: 200
}

export type dashboardTemplatesUpdateResponseSuccess = dashboardTemplatesUpdateResponse200 & {
    headers: Headers
}
export type dashboardTemplatesUpdateResponse = dashboardTemplatesUpdateResponseSuccess

export const getDashboardTemplatesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

export const dashboardTemplatesUpdate = async (
    projectId: string,
    id: string,
    dashboardTemplateApi: NonReadonly<DashboardTemplateApi>,
    options?: RequestInit
): Promise<dashboardTemplatesUpdateResponse> => {
    return apiMutator<dashboardTemplatesUpdateResponse>(getDashboardTemplatesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardTemplateApi),
    })
}

export type dashboardTemplatesPartialUpdateResponse200 = {
    data: DashboardTemplateApi
    status: 200
}

export type dashboardTemplatesPartialUpdateResponseSuccess = dashboardTemplatesPartialUpdateResponse200 & {
    headers: Headers
}
export type dashboardTemplatesPartialUpdateResponse = dashboardTemplatesPartialUpdateResponseSuccess

export const getDashboardTemplatesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

export const dashboardTemplatesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDashboardTemplateApi: NonReadonly<PatchedDashboardTemplateApi>,
    options?: RequestInit
): Promise<dashboardTemplatesPartialUpdateResponse> => {
    return apiMutator<dashboardTemplatesPartialUpdateResponse>(getDashboardTemplatesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDashboardTemplateApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type dashboardTemplatesDestroyResponse405 = {
    data: void
    status: 405
}
export type dashboardTemplatesDestroyResponseError = dashboardTemplatesDestroyResponse405 & {
    headers: Headers
}

export type dashboardTemplatesDestroyResponse = dashboardTemplatesDestroyResponseError

export const getDashboardTemplatesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

export const dashboardTemplatesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<dashboardTemplatesDestroyResponse> => {
    return apiMutator<dashboardTemplatesDestroyResponse>(getDashboardTemplatesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type dashboardTemplatesJsonSchemaRetrieveResponse200 = {
    data: void
    status: 200
}

export type dashboardTemplatesJsonSchemaRetrieveResponseSuccess = dashboardTemplatesJsonSchemaRetrieveResponse200 & {
    headers: Headers
}
export type dashboardTemplatesJsonSchemaRetrieveResponse = dashboardTemplatesJsonSchemaRetrieveResponseSuccess

export const getDashboardTemplatesJsonSchemaRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/dashboard_templates/json_schema/`
}

export const dashboardTemplatesJsonSchemaRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<dashboardTemplatesJsonSchemaRetrieveResponse> => {
    return apiMutator<dashboardTemplatesJsonSchemaRetrieveResponse>(
        getDashboardTemplatesJsonSchemaRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
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

export type eventDefinitionsRetrieveResponse200 = {
    data: void
    status: 200
}

export type eventDefinitionsRetrieveResponseSuccess = eventDefinitionsRetrieveResponse200 & {
    headers: Headers
}
export type eventDefinitionsRetrieveResponse = eventDefinitionsRetrieveResponseSuccess

export const getEventDefinitionsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/`
}

export const eventDefinitionsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<eventDefinitionsRetrieveResponse> => {
    return apiMutator<eventDefinitionsRetrieveResponse>(getEventDefinitionsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type eventDefinitionsCreateResponse201 = {
    data: void
    status: 201
}

export type eventDefinitionsCreateResponseSuccess = eventDefinitionsCreateResponse201 & {
    headers: Headers
}
export type eventDefinitionsCreateResponse = eventDefinitionsCreateResponseSuccess

export const getEventDefinitionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/`
}

export const eventDefinitionsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<eventDefinitionsCreateResponse> => {
    return apiMutator<eventDefinitionsCreateResponse>(getEventDefinitionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export type eventDefinitionsRetrieve2Response200 = {
    data: void
    status: 200
}

export type eventDefinitionsRetrieve2ResponseSuccess = eventDefinitionsRetrieve2Response200 & {
    headers: Headers
}
export type eventDefinitionsRetrieve2Response = eventDefinitionsRetrieve2ResponseSuccess

export const getEventDefinitionsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<eventDefinitionsRetrieve2Response> => {
    return apiMutator<eventDefinitionsRetrieve2Response>(getEventDefinitionsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type eventDefinitionsUpdateResponse200 = {
    data: void
    status: 200
}

export type eventDefinitionsUpdateResponseSuccess = eventDefinitionsUpdateResponse200 & {
    headers: Headers
}
export type eventDefinitionsUpdateResponse = eventDefinitionsUpdateResponseSuccess

export const getEventDefinitionsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsUpdate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<eventDefinitionsUpdateResponse> => {
    return apiMutator<eventDefinitionsUpdateResponse>(getEventDefinitionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
    })
}

export type eventDefinitionsPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type eventDefinitionsPartialUpdateResponseSuccess = eventDefinitionsPartialUpdateResponse200 & {
    headers: Headers
}
export type eventDefinitionsPartialUpdateResponse = eventDefinitionsPartialUpdateResponseSuccess

export const getEventDefinitionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsPartialUpdate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<eventDefinitionsPartialUpdateResponse> => {
    return apiMutator<eventDefinitionsPartialUpdateResponse>(getEventDefinitionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
    })
}

export type eventDefinitionsDestroyResponse204 = {
    data: void
    status: 204
}

export type eventDefinitionsDestroyResponseSuccess = eventDefinitionsDestroyResponse204 & {
    headers: Headers
}
export type eventDefinitionsDestroyResponse = eventDefinitionsDestroyResponseSuccess

export const getEventDefinitionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<eventDefinitionsDestroyResponse> => {
    return apiMutator<eventDefinitionsDestroyResponse>(getEventDefinitionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type eventDefinitionsMetricsRetrieveResponse200 = {
    data: void
    status: 200
}

export type eventDefinitionsMetricsRetrieveResponseSuccess = eventDefinitionsMetricsRetrieveResponse200 & {
    headers: Headers
}
export type eventDefinitionsMetricsRetrieveResponse = eventDefinitionsMetricsRetrieveResponseSuccess

export const getEventDefinitionsMetricsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/metrics/`
}

export const eventDefinitionsMetricsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<eventDefinitionsMetricsRetrieveResponse> => {
    return apiMutator<eventDefinitionsMetricsRetrieveResponse>(getEventDefinitionsMetricsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type eventDefinitionsGolangRetrieveResponse200 = {
    data: void
    status: 200
}

export type eventDefinitionsGolangRetrieveResponseSuccess = eventDefinitionsGolangRetrieveResponse200 & {
    headers: Headers
}
export type eventDefinitionsGolangRetrieveResponse = eventDefinitionsGolangRetrieveResponseSuccess

export const getEventDefinitionsGolangRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/golang/`
}

export const eventDefinitionsGolangRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<eventDefinitionsGolangRetrieveResponse> => {
    return apiMutator<eventDefinitionsGolangRetrieveResponse>(getEventDefinitionsGolangRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type eventDefinitionsPythonRetrieveResponse200 = {
    data: void
    status: 200
}

export type eventDefinitionsPythonRetrieveResponseSuccess = eventDefinitionsPythonRetrieveResponse200 & {
    headers: Headers
}
export type eventDefinitionsPythonRetrieveResponse = eventDefinitionsPythonRetrieveResponseSuccess

export const getEventDefinitionsPythonRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/python/`
}

export const eventDefinitionsPythonRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<eventDefinitionsPythonRetrieveResponse> => {
    return apiMutator<eventDefinitionsPythonRetrieveResponse>(getEventDefinitionsPythonRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type eventDefinitionsTypescriptRetrieveResponse200 = {
    data: void
    status: 200
}

export type eventDefinitionsTypescriptRetrieveResponseSuccess = eventDefinitionsTypescriptRetrieveResponse200 & {
    headers: Headers
}
export type eventDefinitionsTypescriptRetrieveResponse = eventDefinitionsTypescriptRetrieveResponseSuccess

export const getEventDefinitionsTypescriptRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/typescript/`
}

export const eventDefinitionsTypescriptRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<eventDefinitionsTypescriptRetrieveResponse> => {
    return apiMutator<eventDefinitionsTypescriptRetrieveResponse>(getEventDefinitionsTypescriptRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type exportsListResponse200 = {
    data: PaginatedExportedAssetListApi
    status: 200
}

export type exportsListResponseSuccess = exportsListResponse200 & {
    headers: Headers
}
export type exportsListResponse = exportsListResponseSuccess

export const getExportsListUrl = (projectId: string, params?: ExportsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/exports/?${stringifiedParams}`
        : `/api/projects/${projectId}/exports/`
}

export const exportsList = async (
    projectId: string,
    params?: ExportsListParams,
    options?: RequestInit
): Promise<exportsListResponse> => {
    return apiMutator<exportsListResponse>(getExportsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type exportsCreateResponse201 = {
    data: ExportedAssetApi
    status: 201
}

export type exportsCreateResponseSuccess = exportsCreateResponse201 & {
    headers: Headers
}
export type exportsCreateResponse = exportsCreateResponseSuccess

export const getExportsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/exports/`
}

export const exportsCreate = async (
    projectId: string,
    exportedAssetApi: NonReadonly<ExportedAssetApi>,
    options?: RequestInit
): Promise<exportsCreateResponse> => {
    return apiMutator<exportsCreateResponse>(getExportsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(exportedAssetApi),
    })
}

export type exportsRetrieveResponse200 = {
    data: ExportedAssetApi
    status: 200
}

export type exportsRetrieveResponseSuccess = exportsRetrieveResponse200 & {
    headers: Headers
}
export type exportsRetrieveResponse = exportsRetrieveResponseSuccess

export const getExportsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/exports/${id}/`
}

export const exportsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<exportsRetrieveResponse> => {
    return apiMutator<exportsRetrieveResponse>(getExportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type exportsContentRetrieveResponse200 = {
    data: void
    status: 200
}

export type exportsContentRetrieveResponseSuccess = exportsContentRetrieveResponse200 & {
    headers: Headers
}
export type exportsContentRetrieveResponse = exportsContentRetrieveResponseSuccess

export const getExportsContentRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/exports/${id}/content/`
}

export const exportsContentRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<exportsContentRetrieveResponse> => {
    return apiMutator<exportsContentRetrieveResponse>(getExportsContentRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type fileSystemListResponse200 = {
    data: PaginatedFileSystemListApi
    status: 200
}

export type fileSystemListResponseSuccess = fileSystemListResponse200 & {
    headers: Headers
}
export type fileSystemListResponse = fileSystemListResponseSuccess

export const getFileSystemListUrl = (projectId: string, params?: FileSystemListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/file_system/?${stringifiedParams}`
        : `/api/projects/${projectId}/file_system/`
}

export const fileSystemList = async (
    projectId: string,
    params?: FileSystemListParams,
    options?: RequestInit
): Promise<fileSystemListResponse> => {
    return apiMutator<fileSystemListResponse>(getFileSystemListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type fileSystemCreateResponse201 = {
    data: FileSystemApi
    status: 201
}

export type fileSystemCreateResponseSuccess = fileSystemCreateResponse201 & {
    headers: Headers
}
export type fileSystemCreateResponse = fileSystemCreateResponseSuccess

export const getFileSystemCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/`
}

export const fileSystemCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemCreateResponse> => {
    return apiMutator<fileSystemCreateResponse>(getFileSystemCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemRetrieveResponse200 = {
    data: FileSystemApi
    status: 200
}

export type fileSystemRetrieveResponseSuccess = fileSystemRetrieveResponse200 & {
    headers: Headers
}
export type fileSystemRetrieveResponse = fileSystemRetrieveResponseSuccess

export const getFileSystemRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<fileSystemRetrieveResponse> => {
    return apiMutator<fileSystemRetrieveResponse>(getFileSystemRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type fileSystemUpdateResponse200 = {
    data: FileSystemApi
    status: 200
}

export type fileSystemUpdateResponseSuccess = fileSystemUpdateResponse200 & {
    headers: Headers
}
export type fileSystemUpdateResponse = fileSystemUpdateResponseSuccess

export const getFileSystemUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemUpdate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemUpdateResponse> => {
    return apiMutator<fileSystemUpdateResponse>(getFileSystemUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemPartialUpdateResponse200 = {
    data: FileSystemApi
    status: 200
}

export type fileSystemPartialUpdateResponseSuccess = fileSystemPartialUpdateResponse200 & {
    headers: Headers
}
export type fileSystemPartialUpdateResponse = fileSystemPartialUpdateResponseSuccess

export const getFileSystemPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemPartialUpdate = async (
    projectId: string,
    id: string,
    patchedFileSystemApi: NonReadonly<PatchedFileSystemApi>,
    options?: RequestInit
): Promise<fileSystemPartialUpdateResponse> => {
    return apiMutator<fileSystemPartialUpdateResponse>(getFileSystemPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFileSystemApi),
    })
}

export type fileSystemDestroyResponse204 = {
    data: void
    status: 204
}

export type fileSystemDestroyResponseSuccess = fileSystemDestroyResponse204 & {
    headers: Headers
}
export type fileSystemDestroyResponse = fileSystemDestroyResponseSuccess

export const getFileSystemDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<fileSystemDestroyResponse> => {
    return apiMutator<fileSystemDestroyResponse>(getFileSystemDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Get count of all files in a folder.
 */
export type fileSystemCountCreateResponse200 = {
    data: void
    status: 200
}

export type fileSystemCountCreateResponseSuccess = fileSystemCountCreateResponse200 & {
    headers: Headers
}
export type fileSystemCountCreateResponse = fileSystemCountCreateResponseSuccess

export const getFileSystemCountCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/count/`
}

export const fileSystemCountCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemCountCreateResponse> => {
    return apiMutator<fileSystemCountCreateResponse>(getFileSystemCountCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemLinkCreateResponse200 = {
    data: void
    status: 200
}

export type fileSystemLinkCreateResponseSuccess = fileSystemLinkCreateResponse200 & {
    headers: Headers
}
export type fileSystemLinkCreateResponse = fileSystemLinkCreateResponseSuccess

export const getFileSystemLinkCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/link/`
}

export const fileSystemLinkCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemLinkCreateResponse> => {
    return apiMutator<fileSystemLinkCreateResponse>(getFileSystemLinkCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemMoveCreateResponse200 = {
    data: void
    status: 200
}

export type fileSystemMoveCreateResponseSuccess = fileSystemMoveCreateResponse200 & {
    headers: Headers
}
export type fileSystemMoveCreateResponse = fileSystemMoveCreateResponseSuccess

export const getFileSystemMoveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/move/`
}

export const fileSystemMoveCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemMoveCreateResponse> => {
    return apiMutator<fileSystemMoveCreateResponse>(getFileSystemMoveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

/**
 * Get count of all files in a folder.
 */
export type fileSystemCountByPathCreateResponse200 = {
    data: void
    status: 200
}

export type fileSystemCountByPathCreateResponseSuccess = fileSystemCountByPathCreateResponse200 & {
    headers: Headers
}
export type fileSystemCountByPathCreateResponse = fileSystemCountByPathCreateResponseSuccess

export const getFileSystemCountByPathCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/count_by_path/`
}

export const fileSystemCountByPathCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemCountByPathCreateResponse> => {
    return apiMutator<fileSystemCountByPathCreateResponse>(getFileSystemCountByPathCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemLogViewRetrieveResponse200 = {
    data: void
    status: 200
}

export type fileSystemLogViewRetrieveResponseSuccess = fileSystemLogViewRetrieveResponse200 & {
    headers: Headers
}
export type fileSystemLogViewRetrieveResponse = fileSystemLogViewRetrieveResponseSuccess

export const getFileSystemLogViewRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/log_view/`
}

export const fileSystemLogViewRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<fileSystemLogViewRetrieveResponse> => {
    return apiMutator<fileSystemLogViewRetrieveResponse>(getFileSystemLogViewRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type fileSystemLogViewCreateResponse200 = {
    data: void
    status: 200
}

export type fileSystemLogViewCreateResponseSuccess = fileSystemLogViewCreateResponse200 & {
    headers: Headers
}
export type fileSystemLogViewCreateResponse = fileSystemLogViewCreateResponseSuccess

export const getFileSystemLogViewCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/log_view/`
}

export const fileSystemLogViewCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemLogViewCreateResponse> => {
    return apiMutator<fileSystemLogViewCreateResponse>(getFileSystemLogViewCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemUndoDeleteCreateResponse200 = {
    data: void
    status: 200
}

export type fileSystemUndoDeleteCreateResponseSuccess = fileSystemUndoDeleteCreateResponse200 & {
    headers: Headers
}
export type fileSystemUndoDeleteCreateResponse = fileSystemUndoDeleteCreateResponseSuccess

export const getFileSystemUndoDeleteCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/undo_delete/`
}

export const fileSystemUndoDeleteCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemUndoDeleteCreateResponse> => {
    return apiMutator<fileSystemUndoDeleteCreateResponse>(getFileSystemUndoDeleteCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemUnfiledRetrieveResponse200 = {
    data: void
    status: 200
}

export type fileSystemUnfiledRetrieveResponseSuccess = fileSystemUnfiledRetrieveResponse200 & {
    headers: Headers
}
export type fileSystemUnfiledRetrieveResponse = fileSystemUnfiledRetrieveResponseSuccess

export const getFileSystemUnfiledRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/unfiled/`
}

export const fileSystemUnfiledRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<fileSystemUnfiledRetrieveResponse> => {
    return apiMutator<fileSystemUnfiledRetrieveResponse>(getFileSystemUnfiledRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * List all groups of a specific group type. You must pass ?group_type_index= in the URL. To get a list of valid group types, call /api/:project_id/groups_types/
 */
export type groupsListResponse200 = {
    data: PaginatedGroupListApi
    status: 200
}

export type groupsListResponseSuccess = groupsListResponse200 & {
    headers: Headers
}
export type groupsListResponse = groupsListResponseSuccess

export const getGroupsListUrl = (projectId: string, params: GroupsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/`
}

export const groupsList = async (
    projectId: string,
    params: GroupsListParams,
    options?: RequestInit
): Promise<groupsListResponse> => {
    return apiMutator<groupsListResponse>(getGroupsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsCreateResponse201 = {
    data: GroupApi
    status: 201
}

export type groupsCreateResponseSuccess = groupsCreateResponse201 & {
    headers: Headers
}
export type groupsCreateResponse = groupsCreateResponseSuccess

export const getGroupsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/groups/`
}

export const groupsCreate = async (
    projectId: string,
    createGroupApi: CreateGroupApi,
    options?: RequestInit
): Promise<groupsCreateResponse> => {
    return apiMutator<groupsCreateResponse>(getGroupsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createGroupApi),
    })
}

export type groupsActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type groupsActivityRetrieveResponseSuccess = groupsActivityRetrieveResponse200 & {
    headers: Headers
}
export type groupsActivityRetrieveResponse = groupsActivityRetrieveResponseSuccess

export const getGroupsActivityRetrieveUrl = (projectId: string, params: GroupsActivityRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/activity/`
}

export const groupsActivityRetrieve = async (
    projectId: string,
    params: GroupsActivityRetrieveParams,
    options?: RequestInit
): Promise<groupsActivityRetrieveResponse> => {
    return apiMutator<groupsActivityRetrieveResponse>(getGroupsActivityRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsDeletePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type groupsDeletePropertyCreateResponseSuccess = groupsDeletePropertyCreateResponse200 & {
    headers: Headers
}
export type groupsDeletePropertyCreateResponse = groupsDeletePropertyCreateResponseSuccess

export const getGroupsDeletePropertyCreateUrl = (projectId: string, params: GroupsDeletePropertyCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/delete_property/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/delete_property/`
}

export const groupsDeletePropertyCreate = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: GroupsDeletePropertyCreateParams,
    options?: RequestInit
): Promise<groupsDeletePropertyCreateResponse> => {
    return apiMutator<groupsDeletePropertyCreateResponse>(getGroupsDeletePropertyCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupApi),
    })
}

export type groupsFindRetrieveResponse200 = {
    data: void
    status: 200
}

export type groupsFindRetrieveResponseSuccess = groupsFindRetrieveResponse200 & {
    headers: Headers
}
export type groupsFindRetrieveResponse = groupsFindRetrieveResponseSuccess

export const getGroupsFindRetrieveUrl = (projectId: string, params: GroupsFindRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/find/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/find/`
}

export const groupsFindRetrieve = async (
    projectId: string,
    params: GroupsFindRetrieveParams,
    options?: RequestInit
): Promise<groupsFindRetrieveResponse> => {
    return apiMutator<groupsFindRetrieveResponse>(getGroupsFindRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsPropertyDefinitionsRetrieveResponse200 = {
    data: void
    status: 200
}

export type groupsPropertyDefinitionsRetrieveResponseSuccess = groupsPropertyDefinitionsRetrieveResponse200 & {
    headers: Headers
}
export type groupsPropertyDefinitionsRetrieveResponse = groupsPropertyDefinitionsRetrieveResponseSuccess

export const getGroupsPropertyDefinitionsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/groups/property_definitions/`
}

export const groupsPropertyDefinitionsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<groupsPropertyDefinitionsRetrieveResponse> => {
    return apiMutator<groupsPropertyDefinitionsRetrieveResponse>(getGroupsPropertyDefinitionsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type groupsPropertyValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type groupsPropertyValuesRetrieveResponseSuccess = groupsPropertyValuesRetrieveResponse200 & {
    headers: Headers
}
export type groupsPropertyValuesRetrieveResponse = groupsPropertyValuesRetrieveResponseSuccess

export const getGroupsPropertyValuesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/groups/property_values/`
}

export const groupsPropertyValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<groupsPropertyValuesRetrieveResponse> => {
    return apiMutator<groupsPropertyValuesRetrieveResponse>(getGroupsPropertyValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type groupsRelatedRetrieveResponse200 = {
    data: void
    status: 200
}

export type groupsRelatedRetrieveResponseSuccess = groupsRelatedRetrieveResponse200 & {
    headers: Headers
}
export type groupsRelatedRetrieveResponse = groupsRelatedRetrieveResponseSuccess

export const getGroupsRelatedRetrieveUrl = (projectId: string, params: GroupsRelatedRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/related/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/related/`
}

export const groupsRelatedRetrieve = async (
    projectId: string,
    params: GroupsRelatedRetrieveParams,
    options?: RequestInit
): Promise<groupsRelatedRetrieveResponse> => {
    return apiMutator<groupsRelatedRetrieveResponse>(getGroupsRelatedRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsUpdatePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type groupsUpdatePropertyCreateResponseSuccess = groupsUpdatePropertyCreateResponse200 & {
    headers: Headers
}
export type groupsUpdatePropertyCreateResponse = groupsUpdatePropertyCreateResponseSuccess

export const getGroupsUpdatePropertyCreateUrl = (projectId: string, params: GroupsUpdatePropertyCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/update_property/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/update_property/`
}

export const groupsUpdatePropertyCreate = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: GroupsUpdatePropertyCreateParams,
    options?: RequestInit
): Promise<groupsUpdatePropertyCreateResponse> => {
    return apiMutator<groupsUpdatePropertyCreateResponse>(getGroupsUpdatePropertyCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupApi),
    })
}

export type insightsSharingListResponse200 = {
    data: SharingConfigurationApi[]
    status: 200
}

export type insightsSharingListResponseSuccess = insightsSharingListResponse200 & {
    headers: Headers
}
export type insightsSharingListResponse = insightsSharingListResponseSuccess

export const getInsightsSharingListUrl = (projectId: string, insightId: number) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/`
}

export const insightsSharingList = async (
    projectId: string,
    insightId: number,
    options?: RequestInit
): Promise<insightsSharingListResponse> => {
    return apiMutator<insightsSharingListResponse>(getInsightsSharingListUrl(projectId, insightId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new password for the sharing configuration.
 */
export type insightsSharingPasswordsCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type insightsSharingPasswordsCreateResponseSuccess = insightsSharingPasswordsCreateResponse200 & {
    headers: Headers
}
export type insightsSharingPasswordsCreateResponse = insightsSharingPasswordsCreateResponseSuccess

export const getInsightsSharingPasswordsCreateUrl = (projectId: string, insightId: number) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/passwords/`
}

export const insightsSharingPasswordsCreate = async (
    projectId: string,
    insightId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<insightsSharingPasswordsCreateResponse> => {
    return apiMutator<insightsSharingPasswordsCreateResponse>(
        getInsightsSharingPasswordsCreateUrl(projectId, insightId),
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
export type insightsSharingPasswordsDestroyResponse204 = {
    data: void
    status: 204
}

export type insightsSharingPasswordsDestroyResponseSuccess = insightsSharingPasswordsDestroyResponse204 & {
    headers: Headers
}
export type insightsSharingPasswordsDestroyResponse = insightsSharingPasswordsDestroyResponseSuccess

export const getInsightsSharingPasswordsDestroyUrl = (projectId: string, insightId: number, passwordId: string) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/passwords/${passwordId}/`
}

export const insightsSharingPasswordsDestroy = async (
    projectId: string,
    insightId: number,
    passwordId: string,
    options?: RequestInit
): Promise<insightsSharingPasswordsDestroyResponse> => {
    return apiMutator<insightsSharingPasswordsDestroyResponse>(
        getInsightsSharingPasswordsDestroyUrl(projectId, insightId, passwordId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type insightsSharingRefreshCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type insightsSharingRefreshCreateResponseSuccess = insightsSharingRefreshCreateResponse200 & {
    headers: Headers
}
export type insightsSharingRefreshCreateResponse = insightsSharingRefreshCreateResponseSuccess

export const getInsightsSharingRefreshCreateUrl = (projectId: string, insightId: number) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/refresh/`
}

export const insightsSharingRefreshCreate = async (
    projectId: string,
    insightId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<insightsSharingRefreshCreateResponse> => {
    return apiMutator<insightsSharingRefreshCreateResponse>(getInsightsSharingRefreshCreateUrl(projectId, insightId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

export type integrationsList2Response200 = {
    data: PaginatedIntegrationListApi
    status: 200
}

export type integrationsList2ResponseSuccess = integrationsList2Response200 & {
    headers: Headers
}
export type integrationsList2Response = integrationsList2ResponseSuccess

export const getIntegrationsList2Url = (projectId: string, params?: IntegrationsList2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/integrations/?${stringifiedParams}`
        : `/api/projects/${projectId}/integrations/`
}

export const integrationsList2 = async (
    projectId: string,
    params?: IntegrationsList2Params,
    options?: RequestInit
): Promise<integrationsList2Response> => {
    return apiMutator<integrationsList2Response>(getIntegrationsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type integrationsCreateResponse201 = {
    data: IntegrationApi
    status: 201
}

export type integrationsCreateResponseSuccess = integrationsCreateResponse201 & {
    headers: Headers
}
export type integrationsCreateResponse = integrationsCreateResponseSuccess

export const getIntegrationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/`
}

export const integrationsCreate = async (
    projectId: string,
    integrationApi: NonReadonly<IntegrationApi>,
    options?: RequestInit
): Promise<integrationsCreateResponse> => {
    return apiMutator<integrationsCreateResponse>(getIntegrationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationApi),
    })
}

export type integrationsRetrieve2Response200 = {
    data: IntegrationApi
    status: 200
}

export type integrationsRetrieve2ResponseSuccess = integrationsRetrieve2Response200 & {
    headers: Headers
}
export type integrationsRetrieve2Response = integrationsRetrieve2ResponseSuccess

export const getIntegrationsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/`
}

export const integrationsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsRetrieve2Response> => {
    return apiMutator<integrationsRetrieve2Response>(getIntegrationsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type integrationsDestroyResponse204 = {
    data: void
    status: 204
}

export type integrationsDestroyResponseSuccess = integrationsDestroyResponse204 & {
    headers: Headers
}
export type integrationsDestroyResponse = integrationsDestroyResponseSuccess

export const getIntegrationsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/`
}

export const integrationsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsDestroyResponse> => {
    return apiMutator<integrationsDestroyResponse>(getIntegrationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type integrationsChannelsRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsChannelsRetrieveResponseSuccess = integrationsChannelsRetrieveResponse200 & {
    headers: Headers
}
export type integrationsChannelsRetrieveResponse = integrationsChannelsRetrieveResponseSuccess

export const getIntegrationsChannelsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/channels/`
}

export const integrationsChannelsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsChannelsRetrieveResponse> => {
    return apiMutator<integrationsChannelsRetrieveResponse>(getIntegrationsChannelsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type integrationsClickupListsRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsClickupListsRetrieveResponseSuccess = integrationsClickupListsRetrieveResponse200 & {
    headers: Headers
}
export type integrationsClickupListsRetrieveResponse = integrationsClickupListsRetrieveResponseSuccess

export const getIntegrationsClickupListsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_lists/`
}

export const integrationsClickupListsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsClickupListsRetrieveResponse> => {
    return apiMutator<integrationsClickupListsRetrieveResponse>(getIntegrationsClickupListsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type integrationsClickupSpacesRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsClickupSpacesRetrieveResponseSuccess = integrationsClickupSpacesRetrieveResponse200 & {
    headers: Headers
}
export type integrationsClickupSpacesRetrieveResponse = integrationsClickupSpacesRetrieveResponseSuccess

export const getIntegrationsClickupSpacesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_spaces/`
}

export const integrationsClickupSpacesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsClickupSpacesRetrieveResponse> => {
    return apiMutator<integrationsClickupSpacesRetrieveResponse>(
        getIntegrationsClickupSpacesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsClickupWorkspacesRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsClickupWorkspacesRetrieveResponseSuccess = integrationsClickupWorkspacesRetrieveResponse200 & {
    headers: Headers
}
export type integrationsClickupWorkspacesRetrieveResponse = integrationsClickupWorkspacesRetrieveResponseSuccess

export const getIntegrationsClickupWorkspacesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_workspaces/`
}

export const integrationsClickupWorkspacesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsClickupWorkspacesRetrieveResponse> => {
    return apiMutator<integrationsClickupWorkspacesRetrieveResponse>(
        getIntegrationsClickupWorkspacesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsEmailVerifyCreateResponse200 = {
    data: void
    status: 200
}

export type integrationsEmailVerifyCreateResponseSuccess = integrationsEmailVerifyCreateResponse200 & {
    headers: Headers
}
export type integrationsEmailVerifyCreateResponse = integrationsEmailVerifyCreateResponseSuccess

export const getIntegrationsEmailVerifyCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/email/verify/`
}

export const integrationsEmailVerifyCreate = async (
    projectId: string,
    id: number,
    integrationApi: NonReadonly<IntegrationApi>,
    options?: RequestInit
): Promise<integrationsEmailVerifyCreateResponse> => {
    return apiMutator<integrationsEmailVerifyCreateResponse>(getIntegrationsEmailVerifyCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationApi),
    })
}

export type integrationsGithubReposRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsGithubReposRetrieveResponseSuccess = integrationsGithubReposRetrieveResponse200 & {
    headers: Headers
}
export type integrationsGithubReposRetrieveResponse = integrationsGithubReposRetrieveResponseSuccess

export const getIntegrationsGithubReposRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/github_repos/`
}

export const integrationsGithubReposRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsGithubReposRetrieveResponse> => {
    return apiMutator<integrationsGithubReposRetrieveResponse>(getIntegrationsGithubReposRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type integrationsGoogleAccessibleAccountsRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsGoogleAccessibleAccountsRetrieveResponseSuccess =
    integrationsGoogleAccessibleAccountsRetrieveResponse200 & {
        headers: Headers
    }
export type integrationsGoogleAccessibleAccountsRetrieveResponse =
    integrationsGoogleAccessibleAccountsRetrieveResponseSuccess

export const getIntegrationsGoogleAccessibleAccountsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/google_accessible_accounts/`
}

export const integrationsGoogleAccessibleAccountsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsGoogleAccessibleAccountsRetrieveResponse> => {
    return apiMutator<integrationsGoogleAccessibleAccountsRetrieveResponse>(
        getIntegrationsGoogleAccessibleAccountsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsGoogleConversionActionsRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsGoogleConversionActionsRetrieveResponseSuccess =
    integrationsGoogleConversionActionsRetrieveResponse200 & {
        headers: Headers
    }
export type integrationsGoogleConversionActionsRetrieveResponse =
    integrationsGoogleConversionActionsRetrieveResponseSuccess

export const getIntegrationsGoogleConversionActionsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/google_conversion_actions/`
}

export const integrationsGoogleConversionActionsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsGoogleConversionActionsRetrieveResponse> => {
    return apiMutator<integrationsGoogleConversionActionsRetrieveResponse>(
        getIntegrationsGoogleConversionActionsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsJiraProjectsRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsJiraProjectsRetrieveResponseSuccess = integrationsJiraProjectsRetrieveResponse200 & {
    headers: Headers
}
export type integrationsJiraProjectsRetrieveResponse = integrationsJiraProjectsRetrieveResponseSuccess

export const getIntegrationsJiraProjectsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/jira_projects/`
}

export const integrationsJiraProjectsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsJiraProjectsRetrieveResponse> => {
    return apiMutator<integrationsJiraProjectsRetrieveResponse>(getIntegrationsJiraProjectsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type integrationsLinearTeamsRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsLinearTeamsRetrieveResponseSuccess = integrationsLinearTeamsRetrieveResponse200 & {
    headers: Headers
}
export type integrationsLinearTeamsRetrieveResponse = integrationsLinearTeamsRetrieveResponseSuccess

export const getIntegrationsLinearTeamsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linear_teams/`
}

export const integrationsLinearTeamsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsLinearTeamsRetrieveResponse> => {
    return apiMutator<integrationsLinearTeamsRetrieveResponse>(getIntegrationsLinearTeamsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type integrationsLinkedinAdsAccountsRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsLinkedinAdsAccountsRetrieveResponseSuccess =
    integrationsLinkedinAdsAccountsRetrieveResponse200 & {
        headers: Headers
    }
export type integrationsLinkedinAdsAccountsRetrieveResponse = integrationsLinkedinAdsAccountsRetrieveResponseSuccess

export const getIntegrationsLinkedinAdsAccountsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linkedin_ads_accounts/`
}

export const integrationsLinkedinAdsAccountsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsLinkedinAdsAccountsRetrieveResponse> => {
    return apiMutator<integrationsLinkedinAdsAccountsRetrieveResponse>(
        getIntegrationsLinkedinAdsAccountsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsLinkedinAdsConversionRulesRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsLinkedinAdsConversionRulesRetrieveResponseSuccess =
    integrationsLinkedinAdsConversionRulesRetrieveResponse200 & {
        headers: Headers
    }
export type integrationsLinkedinAdsConversionRulesRetrieveResponse =
    integrationsLinkedinAdsConversionRulesRetrieveResponseSuccess

export const getIntegrationsLinkedinAdsConversionRulesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linkedin_ads_conversion_rules/`
}

export const integrationsLinkedinAdsConversionRulesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsLinkedinAdsConversionRulesRetrieveResponse> => {
    return apiMutator<integrationsLinkedinAdsConversionRulesRetrieveResponse>(
        getIntegrationsLinkedinAdsConversionRulesRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsTwilioPhoneNumbersRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsTwilioPhoneNumbersRetrieveResponseSuccess =
    integrationsTwilioPhoneNumbersRetrieveResponse200 & {
        headers: Headers
    }
export type integrationsTwilioPhoneNumbersRetrieveResponse = integrationsTwilioPhoneNumbersRetrieveResponseSuccess

export const getIntegrationsTwilioPhoneNumbersRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/twilio_phone_numbers/`
}

export const integrationsTwilioPhoneNumbersRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsTwilioPhoneNumbersRetrieveResponse> => {
    return apiMutator<integrationsTwilioPhoneNumbersRetrieveResponse>(
        getIntegrationsTwilioPhoneNumbersRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsAuthorizeRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsAuthorizeRetrieveResponseSuccess = integrationsAuthorizeRetrieveResponse200 & {
    headers: Headers
}
export type integrationsAuthorizeRetrieveResponse = integrationsAuthorizeRetrieveResponseSuccess

export const getIntegrationsAuthorizeRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/authorize/`
}

export const integrationsAuthorizeRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<integrationsAuthorizeRetrieveResponse> => {
    return apiMutator<integrationsAuthorizeRetrieveResponse>(getIntegrationsAuthorizeRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type propertyDefinitionsListResponse200 = {
    data: PaginatedPropertyDefinitionListApi
    status: 200
}

export type propertyDefinitionsListResponseSuccess = propertyDefinitionsListResponse200 & {
    headers: Headers
}
export type propertyDefinitionsListResponse = propertyDefinitionsListResponseSuccess

export const getPropertyDefinitionsListUrl = (projectId: string, params?: PropertyDefinitionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/property_definitions/?${stringifiedParams}`
        : `/api/projects/${projectId}/property_definitions/`
}

export const propertyDefinitionsList = async (
    projectId: string,
    params?: PropertyDefinitionsListParams,
    options?: RequestInit
): Promise<propertyDefinitionsListResponse> => {
    return apiMutator<propertyDefinitionsListResponse>(getPropertyDefinitionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type propertyDefinitionsRetrieveResponse200 = {
    data: PropertyDefinitionApi
    status: 200
}

export type propertyDefinitionsRetrieveResponseSuccess = propertyDefinitionsRetrieveResponse200 & {
    headers: Headers
}
export type propertyDefinitionsRetrieveResponse = propertyDefinitionsRetrieveResponseSuccess

export const getPropertyDefinitionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/property_definitions/${id}/`
}

export const propertyDefinitionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<propertyDefinitionsRetrieveResponse> => {
    return apiMutator<propertyDefinitionsRetrieveResponse>(getPropertyDefinitionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type propertyDefinitionsUpdateResponse200 = {
    data: PropertyDefinitionApi
    status: 200
}

export type propertyDefinitionsUpdateResponseSuccess = propertyDefinitionsUpdateResponse200 & {
    headers: Headers
}
export type propertyDefinitionsUpdateResponse = propertyDefinitionsUpdateResponseSuccess

export const getPropertyDefinitionsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/property_definitions/${id}/`
}

export const propertyDefinitionsUpdate = async (
    projectId: string,
    id: string,
    propertyDefinitionApi: NonReadonly<PropertyDefinitionApi>,
    options?: RequestInit
): Promise<propertyDefinitionsUpdateResponse> => {
    return apiMutator<propertyDefinitionsUpdateResponse>(getPropertyDefinitionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(propertyDefinitionApi),
    })
}

export type propertyDefinitionsPartialUpdateResponse200 = {
    data: PropertyDefinitionApi
    status: 200
}

export type propertyDefinitionsPartialUpdateResponseSuccess = propertyDefinitionsPartialUpdateResponse200 & {
    headers: Headers
}
export type propertyDefinitionsPartialUpdateResponse = propertyDefinitionsPartialUpdateResponseSuccess

export const getPropertyDefinitionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/property_definitions/${id}/`
}

export const propertyDefinitionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedPropertyDefinitionApi: NonReadonly<PatchedPropertyDefinitionApi>,
    options?: RequestInit
): Promise<propertyDefinitionsPartialUpdateResponse> => {
    return apiMutator<propertyDefinitionsPartialUpdateResponse>(getPropertyDefinitionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedPropertyDefinitionApi),
    })
}

export type propertyDefinitionsDestroyResponse204 = {
    data: void
    status: 204
}

export type propertyDefinitionsDestroyResponseSuccess = propertyDefinitionsDestroyResponse204 & {
    headers: Headers
}
export type propertyDefinitionsDestroyResponse = propertyDefinitionsDestroyResponseSuccess

export const getPropertyDefinitionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/property_definitions/${id}/`
}

export const propertyDefinitionsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<propertyDefinitionsDestroyResponse> => {
    return apiMutator<propertyDefinitionsDestroyResponse>(getPropertyDefinitionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Allows a caller to provide a list of event names and a single property name
Returns a map of the event names to a boolean representing whether that property has ever been seen with that event_name
 */
export type propertyDefinitionsSeenTogetherRetrieveResponse200 = {
    data: void
    status: 200
}

export type propertyDefinitionsSeenTogetherRetrieveResponseSuccess =
    propertyDefinitionsSeenTogetherRetrieveResponse200 & {
        headers: Headers
    }
export type propertyDefinitionsSeenTogetherRetrieveResponse = propertyDefinitionsSeenTogetherRetrieveResponseSuccess

export const getPropertyDefinitionsSeenTogetherRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/property_definitions/seen_together/`
}

export const propertyDefinitionsSeenTogetherRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<propertyDefinitionsSeenTogetherRetrieveResponse> => {
    return apiMutator<propertyDefinitionsSeenTogetherRetrieveResponse>(
        getPropertyDefinitionsSeenTogetherRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, read, update and delete scheduled changes.
 */
export type scheduledChangesListResponse200 = {
    data: PaginatedScheduledChangeListApi
    status: 200
}

export type scheduledChangesListResponseSuccess = scheduledChangesListResponse200 & {
    headers: Headers
}
export type scheduledChangesListResponse = scheduledChangesListResponseSuccess

export const getScheduledChangesListUrl = (projectId: string, params?: ScheduledChangesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/scheduled_changes/?${stringifiedParams}`
        : `/api/projects/${projectId}/scheduled_changes/`
}

export const scheduledChangesList = async (
    projectId: string,
    params?: ScheduledChangesListParams,
    options?: RequestInit
): Promise<scheduledChangesListResponse> => {
    return apiMutator<scheduledChangesListResponse>(getScheduledChangesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export type scheduledChangesCreateResponse201 = {
    data: ScheduledChangeApi
    status: 201
}

export type scheduledChangesCreateResponseSuccess = scheduledChangesCreateResponse201 & {
    headers: Headers
}
export type scheduledChangesCreateResponse = scheduledChangesCreateResponseSuccess

export const getScheduledChangesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/scheduled_changes/`
}

export const scheduledChangesCreate = async (
    projectId: string,
    scheduledChangeApi: NonReadonly<ScheduledChangeApi>,
    options?: RequestInit
): Promise<scheduledChangesCreateResponse> => {
    return apiMutator<scheduledChangesCreateResponse>(getScheduledChangesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(scheduledChangeApi),
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export type scheduledChangesRetrieveResponse200 = {
    data: ScheduledChangeApi
    status: 200
}

export type scheduledChangesRetrieveResponseSuccess = scheduledChangesRetrieveResponse200 & {
    headers: Headers
}
export type scheduledChangesRetrieveResponse = scheduledChangesRetrieveResponseSuccess

export const getScheduledChangesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<scheduledChangesRetrieveResponse> => {
    return apiMutator<scheduledChangesRetrieveResponse>(getScheduledChangesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export type scheduledChangesUpdateResponse200 = {
    data: ScheduledChangeApi
    status: 200
}

export type scheduledChangesUpdateResponseSuccess = scheduledChangesUpdateResponse200 & {
    headers: Headers
}
export type scheduledChangesUpdateResponse = scheduledChangesUpdateResponseSuccess

export const getScheduledChangesUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesUpdate = async (
    projectId: string,
    id: number,
    scheduledChangeApi: NonReadonly<ScheduledChangeApi>,
    options?: RequestInit
): Promise<scheduledChangesUpdateResponse> => {
    return apiMutator<scheduledChangesUpdateResponse>(getScheduledChangesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(scheduledChangeApi),
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export type scheduledChangesPartialUpdateResponse200 = {
    data: ScheduledChangeApi
    status: 200
}

export type scheduledChangesPartialUpdateResponseSuccess = scheduledChangesPartialUpdateResponse200 & {
    headers: Headers
}
export type scheduledChangesPartialUpdateResponse = scheduledChangesPartialUpdateResponseSuccess

export const getScheduledChangesPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesPartialUpdate = async (
    projectId: string,
    id: number,
    patchedScheduledChangeApi: NonReadonly<PatchedScheduledChangeApi>,
    options?: RequestInit
): Promise<scheduledChangesPartialUpdateResponse> => {
    return apiMutator<scheduledChangesPartialUpdateResponse>(getScheduledChangesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedScheduledChangeApi),
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export type scheduledChangesDestroyResponse204 = {
    data: void
    status: 204
}

export type scheduledChangesDestroyResponseSuccess = scheduledChangesDestroyResponse204 & {
    headers: Headers
}
export type scheduledChangesDestroyResponse = scheduledChangesDestroyResponseSuccess

export const getScheduledChangesDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<scheduledChangesDestroyResponse> => {
    return apiMutator<scheduledChangesDestroyResponse>(getScheduledChangesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type sessionRecordingsSharingListResponse200 = {
    data: SharingConfigurationApi[]
    status: 200
}

export type sessionRecordingsSharingListResponseSuccess = sessionRecordingsSharingListResponse200 & {
    headers: Headers
}
export type sessionRecordingsSharingListResponse = sessionRecordingsSharingListResponseSuccess

export const getSessionRecordingsSharingListUrl = (projectId: string, recordingId: string) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/`
}

export const sessionRecordingsSharingList = async (
    projectId: string,
    recordingId: string,
    options?: RequestInit
): Promise<sessionRecordingsSharingListResponse> => {
    return apiMutator<sessionRecordingsSharingListResponse>(
        getSessionRecordingsSharingListUrl(projectId, recordingId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create a new password for the sharing configuration.
 */
export type sessionRecordingsSharingPasswordsCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type sessionRecordingsSharingPasswordsCreateResponseSuccess =
    sessionRecordingsSharingPasswordsCreateResponse200 & {
        headers: Headers
    }
export type sessionRecordingsSharingPasswordsCreateResponse = sessionRecordingsSharingPasswordsCreateResponseSuccess

export const getSessionRecordingsSharingPasswordsCreateUrl = (projectId: string, recordingId: string) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/passwords/`
}

export const sessionRecordingsSharingPasswordsCreate = async (
    projectId: string,
    recordingId: string,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<sessionRecordingsSharingPasswordsCreateResponse> => {
    return apiMutator<sessionRecordingsSharingPasswordsCreateResponse>(
        getSessionRecordingsSharingPasswordsCreateUrl(projectId, recordingId),
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
export type sessionRecordingsSharingPasswordsDestroyResponse204 = {
    data: void
    status: 204
}

export type sessionRecordingsSharingPasswordsDestroyResponseSuccess =
    sessionRecordingsSharingPasswordsDestroyResponse204 & {
        headers: Headers
    }
export type sessionRecordingsSharingPasswordsDestroyResponse = sessionRecordingsSharingPasswordsDestroyResponseSuccess

export const getSessionRecordingsSharingPasswordsDestroyUrl = (
    projectId: string,
    recordingId: string,
    passwordId: string
) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/passwords/${passwordId}/`
}

export const sessionRecordingsSharingPasswordsDestroy = async (
    projectId: string,
    recordingId: string,
    passwordId: string,
    options?: RequestInit
): Promise<sessionRecordingsSharingPasswordsDestroyResponse> => {
    return apiMutator<sessionRecordingsSharingPasswordsDestroyResponse>(
        getSessionRecordingsSharingPasswordsDestroyUrl(projectId, recordingId, passwordId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type sessionRecordingsSharingRefreshCreateResponse200 = {
    data: SharingConfigurationApi
    status: 200
}

export type sessionRecordingsSharingRefreshCreateResponseSuccess = sessionRecordingsSharingRefreshCreateResponse200 & {
    headers: Headers
}
export type sessionRecordingsSharingRefreshCreateResponse = sessionRecordingsSharingRefreshCreateResponseSuccess

export const getSessionRecordingsSharingRefreshCreateUrl = (projectId: string, recordingId: string) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/refresh/`
}

export const sessionRecordingsSharingRefreshCreate = async (
    projectId: string,
    recordingId: string,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<sessionRecordingsSharingRefreshCreateResponse> => {
    return apiMutator<sessionRecordingsSharingRefreshCreateResponse>(
        getSessionRecordingsSharingRefreshCreateUrl(projectId, recordingId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sharingConfigurationApi),
        }
    )
}

export type subscriptionsListResponse200 = {
    data: PaginatedSubscriptionListApi
    status: 200
}

export type subscriptionsListResponseSuccess = subscriptionsListResponse200 & {
    headers: Headers
}
export type subscriptionsListResponse = subscriptionsListResponseSuccess

export const getSubscriptionsListUrl = (projectId: string, params?: SubscriptionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/subscriptions/?${stringifiedParams}`
        : `/api/projects/${projectId}/subscriptions/`
}

export const subscriptionsList = async (
    projectId: string,
    params?: SubscriptionsListParams,
    options?: RequestInit
): Promise<subscriptionsListResponse> => {
    return apiMutator<subscriptionsListResponse>(getSubscriptionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type subscriptionsCreateResponse201 = {
    data: SubscriptionApi
    status: 201
}

export type subscriptionsCreateResponseSuccess = subscriptionsCreateResponse201 & {
    headers: Headers
}
export type subscriptionsCreateResponse = subscriptionsCreateResponseSuccess

export const getSubscriptionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/subscriptions/`
}

export const subscriptionsCreate = async (
    projectId: string,
    subscriptionApi: NonReadonly<SubscriptionApi>,
    options?: RequestInit
): Promise<subscriptionsCreateResponse> => {
    return apiMutator<subscriptionsCreateResponse>(getSubscriptionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionApi),
    })
}

export type subscriptionsRetrieveResponse200 = {
    data: SubscriptionApi
    status: 200
}

export type subscriptionsRetrieveResponseSuccess = subscriptionsRetrieveResponse200 & {
    headers: Headers
}
export type subscriptionsRetrieveResponse = subscriptionsRetrieveResponseSuccess

export const getSubscriptionsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<subscriptionsRetrieveResponse> => {
    return apiMutator<subscriptionsRetrieveResponse>(getSubscriptionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type subscriptionsUpdateResponse200 = {
    data: SubscriptionApi
    status: 200
}

export type subscriptionsUpdateResponseSuccess = subscriptionsUpdateResponse200 & {
    headers: Headers
}
export type subscriptionsUpdateResponse = subscriptionsUpdateResponseSuccess

export const getSubscriptionsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsUpdate = async (
    projectId: string,
    id: number,
    subscriptionApi: NonReadonly<SubscriptionApi>,
    options?: RequestInit
): Promise<subscriptionsUpdateResponse> => {
    return apiMutator<subscriptionsUpdateResponse>(getSubscriptionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionApi),
    })
}

export type subscriptionsPartialUpdateResponse200 = {
    data: SubscriptionApi
    status: 200
}

export type subscriptionsPartialUpdateResponseSuccess = subscriptionsPartialUpdateResponse200 & {
    headers: Headers
}
export type subscriptionsPartialUpdateResponse = subscriptionsPartialUpdateResponseSuccess

export const getSubscriptionsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedSubscriptionApi: NonReadonly<PatchedSubscriptionApi>,
    options?: RequestInit
): Promise<subscriptionsPartialUpdateResponse> => {
    return apiMutator<subscriptionsPartialUpdateResponse>(getSubscriptionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSubscriptionApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type subscriptionsDestroyResponse405 = {
    data: void
    status: 405
}
export type subscriptionsDestroyResponseError = subscriptionsDestroyResponse405 & {
    headers: Headers
}

export type subscriptionsDestroyResponse = subscriptionsDestroyResponseError

export const getSubscriptionsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<subscriptionsDestroyResponse> => {
    return apiMutator<subscriptionsDestroyResponse>(getSubscriptionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type usersListResponse200 = {
    data: PaginatedUserListApi
    status: 200
}

export type usersListResponseSuccess = usersListResponse200 & {
    headers: Headers
}
export type usersListResponse = usersListResponseSuccess

export const getUsersListUrl = (params?: UsersListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0 ? `/api/users/?${stringifiedParams}` : `/api/users/`
}

export const usersList = async (params?: UsersListParams, options?: RequestInit): Promise<usersListResponse> => {
    return apiMutator<usersListResponse>(getUsersListUrl(params), {
        ...options,
        method: 'GET',
    })
}

export type usersRetrieveResponse200 = {
    data: UserApi
    status: 200
}

export type usersRetrieveResponseSuccess = usersRetrieveResponse200 & {
    headers: Headers
}
export type usersRetrieveResponse = usersRetrieveResponseSuccess

export const getUsersRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/`
}

export const usersRetrieve = async (uuid: string, options?: RequestInit): Promise<usersRetrieveResponse> => {
    return apiMutator<usersRetrieveResponse>(getUsersRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

export type usersUpdateResponse200 = {
    data: UserApi
    status: 200
}

export type usersUpdateResponseSuccess = usersUpdateResponse200 & {
    headers: Headers
}
export type usersUpdateResponse = usersUpdateResponseSuccess

export const getUsersUpdateUrl = (uuid: string) => {
    return `/api/users/${uuid}/`
}

export const usersUpdate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<usersUpdateResponse> => {
    return apiMutator<usersUpdateResponse>(getUsersUpdateUrl(uuid), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export type usersPartialUpdateResponse200 = {
    data: UserApi
    status: 200
}

export type usersPartialUpdateResponseSuccess = usersPartialUpdateResponse200 & {
    headers: Headers
}
export type usersPartialUpdateResponse = usersPartialUpdateResponseSuccess

export const getUsersPartialUpdateUrl = (uuid: string) => {
    return `/api/users/${uuid}/`
}

export const usersPartialUpdate = async (
    uuid: string,
    patchedUserApi: NonReadonly<PatchedUserApi>,
    options?: RequestInit
): Promise<usersPartialUpdateResponse> => {
    return apiMutator<usersPartialUpdateResponse>(getUsersPartialUpdateUrl(uuid), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUserApi),
    })
}

export type usersDestroyResponse204 = {
    data: void
    status: 204
}

export type usersDestroyResponseSuccess = usersDestroyResponse204 & {
    headers: Headers
}
export type usersDestroyResponse = usersDestroyResponseSuccess

export const getUsersDestroyUrl = (uuid: string) => {
    return `/api/users/${uuid}/`
}

export const usersDestroy = async (uuid: string, options?: RequestInit): Promise<usersDestroyResponse> => {
    return apiMutator<usersDestroyResponse>(getUsersDestroyUrl(uuid), {
        ...options,
        method: 'DELETE',
    })
}

export type usersHedgehogConfigRetrieveResponse200 = {
    data: void
    status: 200
}

export type usersHedgehogConfigRetrieveResponseSuccess = usersHedgehogConfigRetrieveResponse200 & {
    headers: Headers
}
export type usersHedgehogConfigRetrieveResponse = usersHedgehogConfigRetrieveResponseSuccess

export const getUsersHedgehogConfigRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/hedgehog_config/`
}

export const usersHedgehogConfigRetrieve = async (
    uuid: string,
    options?: RequestInit
): Promise<usersHedgehogConfigRetrieveResponse> => {
    return apiMutator<usersHedgehogConfigRetrieveResponse>(getUsersHedgehogConfigRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

export type usersHedgehogConfigPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type usersHedgehogConfigPartialUpdateResponseSuccess = usersHedgehogConfigPartialUpdateResponse200 & {
    headers: Headers
}
export type usersHedgehogConfigPartialUpdateResponse = usersHedgehogConfigPartialUpdateResponseSuccess

export const getUsersHedgehogConfigPartialUpdateUrl = (uuid: string) => {
    return `/api/users/${uuid}/hedgehog_config/`
}

export const usersHedgehogConfigPartialUpdate = async (
    uuid: string,
    patchedUserApi: NonReadonly<PatchedUserApi>,
    options?: RequestInit
): Promise<usersHedgehogConfigPartialUpdateResponse> => {
    return apiMutator<usersHedgehogConfigPartialUpdateResponse>(getUsersHedgehogConfigPartialUpdateUrl(uuid), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUserApi),
    })
}

export type usersScenePersonalisationCreateResponse200 = {
    data: void
    status: 200
}

export type usersScenePersonalisationCreateResponseSuccess = usersScenePersonalisationCreateResponse200 & {
    headers: Headers
}
export type usersScenePersonalisationCreateResponse = usersScenePersonalisationCreateResponseSuccess

export const getUsersScenePersonalisationCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/scene_personalisation/`
}

export const usersScenePersonalisationCreate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<usersScenePersonalisationCreateResponse> => {
    return apiMutator<usersScenePersonalisationCreateResponse>(getUsersScenePersonalisationCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export type usersStart2faSetupRetrieveResponse200 = {
    data: void
    status: 200
}

export type usersStart2faSetupRetrieveResponseSuccess = usersStart2faSetupRetrieveResponse200 & {
    headers: Headers
}
export type usersStart2faSetupRetrieveResponse = usersStart2faSetupRetrieveResponseSuccess

export const getUsersStart2faSetupRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/start_2fa_setup/`
}

export const usersStart2faSetupRetrieve = async (
    uuid: string,
    options?: RequestInit
): Promise<usersStart2faSetupRetrieveResponse> => {
    return apiMutator<usersStart2faSetupRetrieveResponse>(getUsersStart2faSetupRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

/**
 * Generate new backup codes, invalidating any existing ones
 */
export type usersTwoFactorBackupCodesCreateResponse200 = {
    data: void
    status: 200
}

export type usersTwoFactorBackupCodesCreateResponseSuccess = usersTwoFactorBackupCodesCreateResponse200 & {
    headers: Headers
}
export type usersTwoFactorBackupCodesCreateResponse = usersTwoFactorBackupCodesCreateResponseSuccess

export const getUsersTwoFactorBackupCodesCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_backup_codes/`
}

export const usersTwoFactorBackupCodesCreate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<usersTwoFactorBackupCodesCreateResponse> => {
    return apiMutator<usersTwoFactorBackupCodesCreateResponse>(getUsersTwoFactorBackupCodesCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

/**
 * Disable 2FA and remove all related devices
 */
export type usersTwoFactorDisableCreateResponse200 = {
    data: void
    status: 200
}

export type usersTwoFactorDisableCreateResponseSuccess = usersTwoFactorDisableCreateResponse200 & {
    headers: Headers
}
export type usersTwoFactorDisableCreateResponse = usersTwoFactorDisableCreateResponseSuccess

export const getUsersTwoFactorDisableCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_disable/`
}

export const usersTwoFactorDisableCreate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<usersTwoFactorDisableCreateResponse> => {
    return apiMutator<usersTwoFactorDisableCreateResponse>(getUsersTwoFactorDisableCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export type usersTwoFactorStartSetupRetrieveResponse200 = {
    data: void
    status: 200
}

export type usersTwoFactorStartSetupRetrieveResponseSuccess = usersTwoFactorStartSetupRetrieveResponse200 & {
    headers: Headers
}
export type usersTwoFactorStartSetupRetrieveResponse = usersTwoFactorStartSetupRetrieveResponseSuccess

export const getUsersTwoFactorStartSetupRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_start_setup/`
}

export const usersTwoFactorStartSetupRetrieve = async (
    uuid: string,
    options?: RequestInit
): Promise<usersTwoFactorStartSetupRetrieveResponse> => {
    return apiMutator<usersTwoFactorStartSetupRetrieveResponse>(getUsersTwoFactorStartSetupRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get current 2FA status including backup codes if enabled
 */
export type usersTwoFactorStatusRetrieveResponse200 = {
    data: void
    status: 200
}

export type usersTwoFactorStatusRetrieveResponseSuccess = usersTwoFactorStatusRetrieveResponse200 & {
    headers: Headers
}
export type usersTwoFactorStatusRetrieveResponse = usersTwoFactorStatusRetrieveResponseSuccess

export const getUsersTwoFactorStatusRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_status/`
}

export const usersTwoFactorStatusRetrieve = async (
    uuid: string,
    options?: RequestInit
): Promise<usersTwoFactorStatusRetrieveResponse> => {
    return apiMutator<usersTwoFactorStatusRetrieveResponse>(getUsersTwoFactorStatusRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

export type usersTwoFactorValidateCreateResponse200 = {
    data: void
    status: 200
}

export type usersTwoFactorValidateCreateResponseSuccess = usersTwoFactorValidateCreateResponse200 & {
    headers: Headers
}
export type usersTwoFactorValidateCreateResponse = usersTwoFactorValidateCreateResponseSuccess

export const getUsersTwoFactorValidateCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_validate/`
}

export const usersTwoFactorValidateCreate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<usersTwoFactorValidateCreateResponse> => {
    return apiMutator<usersTwoFactorValidateCreateResponse>(getUsersTwoFactorValidateCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export type usersValidate2faCreateResponse200 = {
    data: void
    status: 200
}

export type usersValidate2faCreateResponseSuccess = usersValidate2faCreateResponse200 & {
    headers: Headers
}
export type usersValidate2faCreateResponse = usersValidate2faCreateResponseSuccess

export const getUsersValidate2faCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/validate_2fa/`
}

export const usersValidate2faCreate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<usersValidate2faCreateResponse> => {
    return apiMutator<usersValidate2faCreateResponse>(getUsersValidate2faCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export type usersCancelEmailChangeRequestPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type usersCancelEmailChangeRequestPartialUpdateResponseSuccess =
    usersCancelEmailChangeRequestPartialUpdateResponse200 & {
        headers: Headers
    }
export type usersCancelEmailChangeRequestPartialUpdateResponse =
    usersCancelEmailChangeRequestPartialUpdateResponseSuccess

export const getUsersCancelEmailChangeRequestPartialUpdateUrl = () => {
    return `/api/users/cancel_email_change_request/`
}

export const usersCancelEmailChangeRequestPartialUpdate = async (
    patchedUserApi: NonReadonly<PatchedUserApi>,
    options?: RequestInit
): Promise<usersCancelEmailChangeRequestPartialUpdateResponse> => {
    return apiMutator<usersCancelEmailChangeRequestPartialUpdateResponse>(
        getUsersCancelEmailChangeRequestPartialUpdateUrl(),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedUserApi),
        }
    )
}

export type usersRequestEmailVerificationCreateResponse200 = {
    data: void
    status: 200
}

export type usersRequestEmailVerificationCreateResponseSuccess = usersRequestEmailVerificationCreateResponse200 & {
    headers: Headers
}
export type usersRequestEmailVerificationCreateResponse = usersRequestEmailVerificationCreateResponseSuccess

export const getUsersRequestEmailVerificationCreateUrl = () => {
    return `/api/users/request_email_verification/`
}

export const usersRequestEmailVerificationCreate = async (
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<usersRequestEmailVerificationCreateResponse> => {
    return apiMutator<usersRequestEmailVerificationCreateResponse>(getUsersRequestEmailVerificationCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export type usersVerifyEmailCreateResponse200 = {
    data: void
    status: 200
}

export type usersVerifyEmailCreateResponseSuccess = usersVerifyEmailCreateResponse200 & {
    headers: Headers
}
export type usersVerifyEmailCreateResponse = usersVerifyEmailCreateResponseSuccess

export const getUsersVerifyEmailCreateUrl = () => {
    return `/api/users/verify_email/`
}

export const usersVerifyEmailCreate = async (
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<usersVerifyEmailCreateResponse> => {
    return apiMutator<usersVerifyEmailCreateResponse>(getUsersVerifyEmailCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}
