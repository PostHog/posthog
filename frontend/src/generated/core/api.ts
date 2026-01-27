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
    CommentApi,
    CommentsListParams,
    DashboardTemplateApi,
    DashboardTemplatesListParams,
    DomainsListParams,
    EnterpriseEventDefinitionApi,
    EnterprisePropertyDefinitionApi,
    EventDefinitionsListParams,
    ExportedAssetApi,
    ExportsList2Params,
    ExportsListParams,
    FileSystemApi,
    FileSystemList2Params,
    FileSystemListParams,
    FlagValueValuesRetrieve200Item,
    FlagValueValuesRetrieve400,
    FlagValueValuesRetrieve404,
    FlagValueValuesRetrieveParams,
    IntegrationApi,
    IntegrationsList3Params,
    IntegrationsListParams,
    InvitesListParams,
    List2Params,
    MembersListParams,
    OrganizationDomainApi,
    OrganizationInviteApi,
    OrganizationMemberApi,
    PaginatedAnnotationListApi,
    PaginatedCommentListApi,
    PaginatedDashboardTemplateListApi,
    PaginatedEnterpriseEventDefinitionListApi,
    PaginatedEnterprisePropertyDefinitionListApi,
    PaginatedExportedAssetListApi,
    PaginatedFileSystemListApi,
    PaginatedIntegrationListApi,
    PaginatedOrganizationDomainListApi,
    PaginatedOrganizationInviteListApi,
    PaginatedOrganizationMemberListApi,
    PaginatedProjectBackwardCompatBasicListApi,
    PaginatedRoleListApi,
    PaginatedScheduledChangeListApi,
    PaginatedSubscriptionListApi,
    PaginatedUserListApi,
    PatchedAnnotationApi,
    PatchedCommentApi,
    PatchedDashboardTemplateApi,
    PatchedEnterpriseEventDefinitionApi,
    PatchedEnterprisePropertyDefinitionApi,
    PatchedFileSystemApi,
    PatchedIntegrationApi,
    PatchedOrganizationDomainApi,
    PatchedOrganizationMemberApi,
    PatchedProjectBackwardCompatApi,
    PatchedRoleApi,
    PatchedScheduledChangeApi,
    PatchedSubscriptionApi,
    PatchedUserApi,
    ProjectBackwardCompatApi,
    PropertyDefinitionsListParams,
    RoleApi,
    RolesListParams,
    ScheduledChangeApi,
    ScheduledChangesListParams,
    SharingConfigurationApi,
    SubscriptionApi,
    SubscriptionsList2Params,
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
        ? `/api/environments/${projectId}/exports/?${stringifiedParams}`
        : `/api/environments/${projectId}/exports/`
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
    return `/api/environments/${projectId}/exports/`
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
    return `/api/environments/${projectId}/exports/${id}/`
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
    return `/api/environments/${projectId}/exports/${id}/content/`
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
        ? `/api/environments/${projectId}/file_system/?${stringifiedParams}`
        : `/api/environments/${projectId}/file_system/`
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
    return `/api/environments/${projectId}/file_system/`
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
    return `/api/environments/${projectId}/file_system/${id}/`
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
    return `/api/environments/${projectId}/file_system/${id}/`
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
    return `/api/environments/${projectId}/file_system/${id}/`
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
    return `/api/environments/${projectId}/file_system/${id}/`
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
    return `/api/environments/${projectId}/file_system/${id}/count/`
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
    return `/api/environments/${projectId}/file_system/${id}/link/`
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
    return `/api/environments/${projectId}/file_system/${id}/move/`
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
    return `/api/environments/${projectId}/file_system/count_by_path/`
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
    return `/api/environments/${projectId}/file_system/log_view/`
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
    return `/api/environments/${projectId}/file_system/log_view/`
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
    return `/api/environments/${projectId}/file_system/undo_delete/`
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
    return `/api/environments/${projectId}/file_system/unfiled/`
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

export type insightsSharingListResponse200 = {
    data: SharingConfigurationApi[]
    status: 200
}

export type insightsSharingListResponseSuccess = insightsSharingListResponse200 & {
    headers: Headers
}
export type insightsSharingListResponse = insightsSharingListResponseSuccess

export const getInsightsSharingListUrl = (projectId: string, insightId: number) => {
    return `/api/environments/${projectId}/insights/${insightId}/sharing/`
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
    return `/api/environments/${projectId}/insights/${insightId}/sharing/passwords/`
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
    return `/api/environments/${projectId}/insights/${insightId}/sharing/passwords/${passwordId}/`
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
    return `/api/environments/${projectId}/insights/${insightId}/sharing/refresh/`
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

export type integrationsListResponse200 = {
    data: PaginatedIntegrationListApi
    status: 200
}

export type integrationsListResponseSuccess = integrationsListResponse200 & {
    headers: Headers
}
export type integrationsListResponse = integrationsListResponseSuccess

export const getIntegrationsListUrl = (projectId: string, params?: IntegrationsListParams) => {
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

export const integrationsList = async (
    projectId: string,
    params?: IntegrationsListParams,
    options?: RequestInit
): Promise<integrationsListResponse> => {
    return apiMutator<integrationsListResponse>(getIntegrationsListUrl(projectId, params), {
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
    return `/api/environments/${projectId}/integrations/`
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

export type integrationsRetrieveResponse200 = {
    data: IntegrationApi
    status: 200
}

export type integrationsRetrieveResponseSuccess = integrationsRetrieveResponse200 & {
    headers: Headers
}
export type integrationsRetrieveResponse = integrationsRetrieveResponseSuccess

export const getIntegrationsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/`
}

export const integrationsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsRetrieveResponse> => {
    return apiMutator<integrationsRetrieveResponse>(getIntegrationsRetrieveUrl(projectId, id), {
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
    return `/api/environments/${projectId}/integrations/${id}/`
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
    return `/api/environments/${projectId}/integrations/${id}/channels/`
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
    return `/api/environments/${projectId}/integrations/${id}/clickup_lists/`
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
    return `/api/environments/${projectId}/integrations/${id}/clickup_spaces/`
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
    return `/api/environments/${projectId}/integrations/${id}/clickup_workspaces/`
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

export type integrationsEmailPartialUpdateResponse200 = {
    data: IntegrationApi
    status: 200
}

export type integrationsEmailPartialUpdateResponseSuccess = integrationsEmailPartialUpdateResponse200 & {
    headers: Headers
}
export type integrationsEmailPartialUpdateResponse = integrationsEmailPartialUpdateResponseSuccess

export const getIntegrationsEmailPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/email/`
}

export const integrationsEmailPartialUpdate = async (
    projectId: string,
    id: number,
    patchedIntegrationApi: NonReadonly<PatchedIntegrationApi>,
    options?: RequestInit
): Promise<integrationsEmailPartialUpdateResponse> => {
    return apiMutator<integrationsEmailPartialUpdateResponse>(getIntegrationsEmailPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedIntegrationApi),
    })
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
    return `/api/environments/${projectId}/integrations/${id}/email/verify/`
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
    return `/api/environments/${projectId}/integrations/${id}/github_repos/`
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
    return `/api/environments/${projectId}/integrations/${id}/google_accessible_accounts/`
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
    return `/api/environments/${projectId}/integrations/${id}/google_conversion_actions/`
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

export type integrationsJiraRetrieveResponse200 = {
    data: void
    status: 200
}

export type integrationsJiraRetrieveResponseSuccess = integrationsJiraRetrieveResponse200 & {
    headers: Headers
}
export type integrationsJiraRetrieveResponse = integrationsJiraRetrieveResponseSuccess

export const getIntegrationsJiraRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/integrations/${id}/jira_projects/`
}

export const integrationsJiraRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsJiraRetrieveResponse> => {
    return apiMutator<integrationsJiraRetrieveResponse>(getIntegrationsJiraRetrieveUrl(projectId, id), {
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
    return `/api/environments/${projectId}/integrations/${id}/linear_teams/`
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
    return `/api/environments/${projectId}/integrations/${id}/linkedin_ads_accounts/`
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
    return `/api/environments/${projectId}/integrations/${id}/linkedin_ads_conversion_rules/`
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
    return `/api/environments/${projectId}/integrations/${id}/twilio_phone_numbers/`
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
    return `/api/environments/${projectId}/integrations/authorize/`
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

export type sessionRecordingsSharingListResponse200 = {
    data: SharingConfigurationApi[]
    status: 200
}

export type sessionRecordingsSharingListResponseSuccess = sessionRecordingsSharingListResponse200 & {
    headers: Headers
}
export type sessionRecordingsSharingListResponse = sessionRecordingsSharingListResponseSuccess

export const getSessionRecordingsSharingListUrl = (projectId: string, recordingId: string) => {
    return `/api/environments/${projectId}/session_recordings/${recordingId}/sharing/`
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
    return `/api/environments/${projectId}/session_recordings/${recordingId}/sharing/passwords/`
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
    return `/api/environments/${projectId}/session_recordings/${recordingId}/sharing/passwords/${passwordId}/`
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
    return `/api/environments/${projectId}/session_recordings/${recordingId}/sharing/refresh/`
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
        ? `/api/environments/${projectId}/subscriptions/?${stringifiedParams}`
        : `/api/environments/${projectId}/subscriptions/`
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
    return `/api/environments/${projectId}/subscriptions/`
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
    return `/api/environments/${projectId}/subscriptions/${id}/`
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
    return `/api/environments/${projectId}/subscriptions/${id}/`
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
    return `/api/environments/${projectId}/subscriptions/${id}/`
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
    return `/api/environments/${projectId}/subscriptions/${id}/`
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

export type eventDefinitionsListResponse200 = {
    data: PaginatedEnterpriseEventDefinitionListApi
    status: 200
}

export type eventDefinitionsListResponseSuccess = eventDefinitionsListResponse200 & {
    headers: Headers
}
export type eventDefinitionsListResponse = eventDefinitionsListResponseSuccess

export const getEventDefinitionsListUrl = (projectId: string, params?: EventDefinitionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/event_definitions/?${stringifiedParams}`
        : `/api/projects/${projectId}/event_definitions/`
}

export const eventDefinitionsList = async (
    projectId: string,
    params?: EventDefinitionsListParams,
    options?: RequestInit
): Promise<eventDefinitionsListResponse> => {
    return apiMutator<eventDefinitionsListResponse>(getEventDefinitionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type eventDefinitionsCreateResponse201 = {
    data: EnterpriseEventDefinitionApi
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
    enterpriseEventDefinitionApi: NonReadonly<EnterpriseEventDefinitionApi>,
    options?: RequestInit
): Promise<eventDefinitionsCreateResponse> => {
    return apiMutator<eventDefinitionsCreateResponse>(getEventDefinitionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(enterpriseEventDefinitionApi),
    })
}

export type eventDefinitionsRetrieveResponse200 = {
    data: EnterpriseEventDefinitionApi
    status: 200
}

export type eventDefinitionsRetrieveResponseSuccess = eventDefinitionsRetrieveResponse200 & {
    headers: Headers
}
export type eventDefinitionsRetrieveResponse = eventDefinitionsRetrieveResponseSuccess

export const getEventDefinitionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<eventDefinitionsRetrieveResponse> => {
    return apiMutator<eventDefinitionsRetrieveResponse>(getEventDefinitionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type eventDefinitionsUpdateResponse200 = {
    data: EnterpriseEventDefinitionApi
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
    enterpriseEventDefinitionApi: NonReadonly<EnterpriseEventDefinitionApi>,
    options?: RequestInit
): Promise<eventDefinitionsUpdateResponse> => {
    return apiMutator<eventDefinitionsUpdateResponse>(getEventDefinitionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(enterpriseEventDefinitionApi),
    })
}

export type eventDefinitionsPartialUpdateResponse200 = {
    data: EnterpriseEventDefinitionApi
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
    patchedEnterpriseEventDefinitionApi: NonReadonly<PatchedEnterpriseEventDefinitionApi>,
    options?: RequestInit
): Promise<eventDefinitionsPartialUpdateResponse> => {
    return apiMutator<eventDefinitionsPartialUpdateResponse>(getEventDefinitionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEnterpriseEventDefinitionApi),
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

export type exportsList2Response200 = {
    data: PaginatedExportedAssetListApi
    status: 200
}

export type exportsList2ResponseSuccess = exportsList2Response200 & {
    headers: Headers
}
export type exportsList2Response = exportsList2ResponseSuccess

export const getExportsList2Url = (projectId: string, params?: ExportsList2Params) => {
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

export const exportsList2 = async (
    projectId: string,
    params?: ExportsList2Params,
    options?: RequestInit
): Promise<exportsList2Response> => {
    return apiMutator<exportsList2Response>(getExportsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type exportsCreate2Response201 = {
    data: ExportedAssetApi
    status: 201
}

export type exportsCreate2ResponseSuccess = exportsCreate2Response201 & {
    headers: Headers
}
export type exportsCreate2Response = exportsCreate2ResponseSuccess

export const getExportsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/exports/`
}

export const exportsCreate2 = async (
    projectId: string,
    exportedAssetApi: NonReadonly<ExportedAssetApi>,
    options?: RequestInit
): Promise<exportsCreate2Response> => {
    return apiMutator<exportsCreate2Response>(getExportsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(exportedAssetApi),
    })
}

export type exportsRetrieve2Response200 = {
    data: ExportedAssetApi
    status: 200
}

export type exportsRetrieve2ResponseSuccess = exportsRetrieve2Response200 & {
    headers: Headers
}
export type exportsRetrieve2Response = exportsRetrieve2ResponseSuccess

export const getExportsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/exports/${id}/`
}

export const exportsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<exportsRetrieve2Response> => {
    return apiMutator<exportsRetrieve2Response>(getExportsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type exportsContentRetrieve2Response200 = {
    data: void
    status: 200
}

export type exportsContentRetrieve2ResponseSuccess = exportsContentRetrieve2Response200 & {
    headers: Headers
}
export type exportsContentRetrieve2Response = exportsContentRetrieve2ResponseSuccess

export const getExportsContentRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/exports/${id}/content/`
}

export const exportsContentRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<exportsContentRetrieve2Response> => {
    return apiMutator<exportsContentRetrieve2Response>(getExportsContentRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type fileSystemList2Response200 = {
    data: PaginatedFileSystemListApi
    status: 200
}

export type fileSystemList2ResponseSuccess = fileSystemList2Response200 & {
    headers: Headers
}
export type fileSystemList2Response = fileSystemList2ResponseSuccess

export const getFileSystemList2Url = (projectId: string, params?: FileSystemList2Params) => {
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

export const fileSystemList2 = async (
    projectId: string,
    params?: FileSystemList2Params,
    options?: RequestInit
): Promise<fileSystemList2Response> => {
    return apiMutator<fileSystemList2Response>(getFileSystemList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type fileSystemCreate2Response201 = {
    data: FileSystemApi
    status: 201
}

export type fileSystemCreate2ResponseSuccess = fileSystemCreate2Response201 & {
    headers: Headers
}
export type fileSystemCreate2Response = fileSystemCreate2ResponseSuccess

export const getFileSystemCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/`
}

export const fileSystemCreate2 = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemCreate2Response> => {
    return apiMutator<fileSystemCreate2Response>(getFileSystemCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemRetrieve2Response200 = {
    data: FileSystemApi
    status: 200
}

export type fileSystemRetrieve2ResponseSuccess = fileSystemRetrieve2Response200 & {
    headers: Headers
}
export type fileSystemRetrieve2Response = fileSystemRetrieve2ResponseSuccess

export const getFileSystemRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<fileSystemRetrieve2Response> => {
    return apiMutator<fileSystemRetrieve2Response>(getFileSystemRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type fileSystemUpdate2Response200 = {
    data: FileSystemApi
    status: 200
}

export type fileSystemUpdate2ResponseSuccess = fileSystemUpdate2Response200 & {
    headers: Headers
}
export type fileSystemUpdate2Response = fileSystemUpdate2ResponseSuccess

export const getFileSystemUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemUpdate2 = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemUpdate2Response> => {
    return apiMutator<fileSystemUpdate2Response>(getFileSystemUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemPartialUpdate2Response200 = {
    data: FileSystemApi
    status: 200
}

export type fileSystemPartialUpdate2ResponseSuccess = fileSystemPartialUpdate2Response200 & {
    headers: Headers
}
export type fileSystemPartialUpdate2Response = fileSystemPartialUpdate2ResponseSuccess

export const getFileSystemPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedFileSystemApi: NonReadonly<PatchedFileSystemApi>,
    options?: RequestInit
): Promise<fileSystemPartialUpdate2Response> => {
    return apiMutator<fileSystemPartialUpdate2Response>(getFileSystemPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFileSystemApi),
    })
}

export type fileSystemDestroy2Response204 = {
    data: void
    status: 204
}

export type fileSystemDestroy2ResponseSuccess = fileSystemDestroy2Response204 & {
    headers: Headers
}
export type fileSystemDestroy2Response = fileSystemDestroy2ResponseSuccess

export const getFileSystemDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<fileSystemDestroy2Response> => {
    return apiMutator<fileSystemDestroy2Response>(getFileSystemDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Get count of all files in a folder.
 */
export type fileSystemCountCreate2Response200 = {
    data: void
    status: 200
}

export type fileSystemCountCreate2ResponseSuccess = fileSystemCountCreate2Response200 & {
    headers: Headers
}
export type fileSystemCountCreate2Response = fileSystemCountCreate2ResponseSuccess

export const getFileSystemCountCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/count/`
}

export const fileSystemCountCreate2 = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemCountCreate2Response> => {
    return apiMutator<fileSystemCountCreate2Response>(getFileSystemCountCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemLinkCreate2Response200 = {
    data: void
    status: 200
}

export type fileSystemLinkCreate2ResponseSuccess = fileSystemLinkCreate2Response200 & {
    headers: Headers
}
export type fileSystemLinkCreate2Response = fileSystemLinkCreate2ResponseSuccess

export const getFileSystemLinkCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/link/`
}

export const fileSystemLinkCreate2 = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemLinkCreate2Response> => {
    return apiMutator<fileSystemLinkCreate2Response>(getFileSystemLinkCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemMoveCreate2Response200 = {
    data: void
    status: 200
}

export type fileSystemMoveCreate2ResponseSuccess = fileSystemMoveCreate2Response200 & {
    headers: Headers
}
export type fileSystemMoveCreate2Response = fileSystemMoveCreate2ResponseSuccess

export const getFileSystemMoveCreate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/move/`
}

export const fileSystemMoveCreate2 = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemMoveCreate2Response> => {
    return apiMutator<fileSystemMoveCreate2Response>(getFileSystemMoveCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

/**
 * Get count of all files in a folder.
 */
export type fileSystemCountByPathCreate2Response200 = {
    data: void
    status: 200
}

export type fileSystemCountByPathCreate2ResponseSuccess = fileSystemCountByPathCreate2Response200 & {
    headers: Headers
}
export type fileSystemCountByPathCreate2Response = fileSystemCountByPathCreate2ResponseSuccess

export const getFileSystemCountByPathCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/count_by_path/`
}

export const fileSystemCountByPathCreate2 = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemCountByPathCreate2Response> => {
    return apiMutator<fileSystemCountByPathCreate2Response>(getFileSystemCountByPathCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemLogViewRetrieve2Response200 = {
    data: void
    status: 200
}

export type fileSystemLogViewRetrieve2ResponseSuccess = fileSystemLogViewRetrieve2Response200 & {
    headers: Headers
}
export type fileSystemLogViewRetrieve2Response = fileSystemLogViewRetrieve2ResponseSuccess

export const getFileSystemLogViewRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/log_view/`
}

export const fileSystemLogViewRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<fileSystemLogViewRetrieve2Response> => {
    return apiMutator<fileSystemLogViewRetrieve2Response>(getFileSystemLogViewRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export type fileSystemLogViewCreate2Response200 = {
    data: void
    status: 200
}

export type fileSystemLogViewCreate2ResponseSuccess = fileSystemLogViewCreate2Response200 & {
    headers: Headers
}
export type fileSystemLogViewCreate2Response = fileSystemLogViewCreate2ResponseSuccess

export const getFileSystemLogViewCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/log_view/`
}

export const fileSystemLogViewCreate2 = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemLogViewCreate2Response> => {
    return apiMutator<fileSystemLogViewCreate2Response>(getFileSystemLogViewCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemUndoDeleteCreate2Response200 = {
    data: void
    status: 200
}

export type fileSystemUndoDeleteCreate2ResponseSuccess = fileSystemUndoDeleteCreate2Response200 & {
    headers: Headers
}
export type fileSystemUndoDeleteCreate2Response = fileSystemUndoDeleteCreate2ResponseSuccess

export const getFileSystemUndoDeleteCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/undo_delete/`
}

export const fileSystemUndoDeleteCreate2 = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<fileSystemUndoDeleteCreate2Response> => {
    return apiMutator<fileSystemUndoDeleteCreate2Response>(getFileSystemUndoDeleteCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export type fileSystemUnfiledRetrieve2Response200 = {
    data: void
    status: 200
}

export type fileSystemUnfiledRetrieve2ResponseSuccess = fileSystemUnfiledRetrieve2Response200 & {
    headers: Headers
}
export type fileSystemUnfiledRetrieve2Response = fileSystemUnfiledRetrieve2ResponseSuccess

export const getFileSystemUnfiledRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/unfiled/`
}

export const fileSystemUnfiledRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<fileSystemUnfiledRetrieve2Response> => {
    return apiMutator<fileSystemUnfiledRetrieve2Response>(getFileSystemUnfiledRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get possible values for a feature flag.

Query parameters:
- key: The flag ID (required)
Returns:

- Array of objects with 'name' field containing possible values
 */
export type flagValueValuesRetrieveResponse200 = {
    data: FlagValueValuesRetrieve200Item[]
    status: 200
}

export type flagValueValuesRetrieveResponse400 = {
    data: FlagValueValuesRetrieve400
    status: 400
}

export type flagValueValuesRetrieveResponse404 = {
    data: FlagValueValuesRetrieve404
    status: 404
}

export type flagValueValuesRetrieveResponseSuccess = flagValueValuesRetrieveResponse200 & {
    headers: Headers
}
export type flagValueValuesRetrieveResponseError = (
    | flagValueValuesRetrieveResponse400
    | flagValueValuesRetrieveResponse404
) & {
    headers: Headers
}

export type flagValueValuesRetrieveResponse =
    | flagValueValuesRetrieveResponseSuccess
    | flagValueValuesRetrieveResponseError

export const getFlagValueValuesRetrieveUrl = (projectId: string, params?: FlagValueValuesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/flag_value/values/?${stringifiedParams}`
        : `/api/projects/${projectId}/flag_value/values/`
}

export const flagValueValuesRetrieve = async (
    projectId: string,
    params?: FlagValueValuesRetrieveParams,
    options?: RequestInit
): Promise<flagValueValuesRetrieveResponse> => {
    return apiMutator<flagValueValuesRetrieveResponse>(getFlagValueValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type insightsSharingList2Response200 = {
    data: SharingConfigurationApi[]
    status: 200
}

export type insightsSharingList2ResponseSuccess = insightsSharingList2Response200 & {
    headers: Headers
}
export type insightsSharingList2Response = insightsSharingList2ResponseSuccess

export const getInsightsSharingList2Url = (projectId: string, insightId: number) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/`
}

export const insightsSharingList2 = async (
    projectId: string,
    insightId: number,
    options?: RequestInit
): Promise<insightsSharingList2Response> => {
    return apiMutator<insightsSharingList2Response>(getInsightsSharingList2Url(projectId, insightId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new password for the sharing configuration.
 */
export type insightsSharingPasswordsCreate2Response200 = {
    data: SharingConfigurationApi
    status: 200
}

export type insightsSharingPasswordsCreate2ResponseSuccess = insightsSharingPasswordsCreate2Response200 & {
    headers: Headers
}
export type insightsSharingPasswordsCreate2Response = insightsSharingPasswordsCreate2ResponseSuccess

export const getInsightsSharingPasswordsCreate2Url = (projectId: string, insightId: number) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/passwords/`
}

export const insightsSharingPasswordsCreate2 = async (
    projectId: string,
    insightId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<insightsSharingPasswordsCreate2Response> => {
    return apiMutator<insightsSharingPasswordsCreate2Response>(
        getInsightsSharingPasswordsCreate2Url(projectId, insightId),
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
export type insightsSharingPasswordsDestroy2Response204 = {
    data: void
    status: 204
}

export type insightsSharingPasswordsDestroy2ResponseSuccess = insightsSharingPasswordsDestroy2Response204 & {
    headers: Headers
}
export type insightsSharingPasswordsDestroy2Response = insightsSharingPasswordsDestroy2ResponseSuccess

export const getInsightsSharingPasswordsDestroy2Url = (projectId: string, insightId: number, passwordId: string) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/passwords/${passwordId}/`
}

export const insightsSharingPasswordsDestroy2 = async (
    projectId: string,
    insightId: number,
    passwordId: string,
    options?: RequestInit
): Promise<insightsSharingPasswordsDestroy2Response> => {
    return apiMutator<insightsSharingPasswordsDestroy2Response>(
        getInsightsSharingPasswordsDestroy2Url(projectId, insightId, passwordId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type insightsSharingRefreshCreate2Response200 = {
    data: SharingConfigurationApi
    status: 200
}

export type insightsSharingRefreshCreate2ResponseSuccess = insightsSharingRefreshCreate2Response200 & {
    headers: Headers
}
export type insightsSharingRefreshCreate2Response = insightsSharingRefreshCreate2ResponseSuccess

export const getInsightsSharingRefreshCreate2Url = (projectId: string, insightId: number) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/refresh/`
}

export const insightsSharingRefreshCreate2 = async (
    projectId: string,
    insightId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<insightsSharingRefreshCreate2Response> => {
    return apiMutator<insightsSharingRefreshCreate2Response>(
        getInsightsSharingRefreshCreate2Url(projectId, insightId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sharingConfigurationApi),
        }
    )
}

export type integrationsList3Response200 = {
    data: PaginatedIntegrationListApi
    status: 200
}

export type integrationsList3ResponseSuccess = integrationsList3Response200 & {
    headers: Headers
}
export type integrationsList3Response = integrationsList3ResponseSuccess

export const getIntegrationsList3Url = (projectId: string, params?: IntegrationsList3Params) => {
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

export const integrationsList3 = async (
    projectId: string,
    params?: IntegrationsList3Params,
    options?: RequestInit
): Promise<integrationsList3Response> => {
    return apiMutator<integrationsList3Response>(getIntegrationsList3Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type integrationsCreate2Response201 = {
    data: IntegrationApi
    status: 201
}

export type integrationsCreate2ResponseSuccess = integrationsCreate2Response201 & {
    headers: Headers
}
export type integrationsCreate2Response = integrationsCreate2ResponseSuccess

export const getIntegrationsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/`
}

export const integrationsCreate2 = async (
    projectId: string,
    integrationApi: NonReadonly<IntegrationApi>,
    options?: RequestInit
): Promise<integrationsCreate2Response> => {
    return apiMutator<integrationsCreate2Response>(getIntegrationsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationApi),
    })
}

export type integrationsRetrieve3Response200 = {
    data: IntegrationApi
    status: 200
}

export type integrationsRetrieve3ResponseSuccess = integrationsRetrieve3Response200 & {
    headers: Headers
}
export type integrationsRetrieve3Response = integrationsRetrieve3ResponseSuccess

export const getIntegrationsRetrieve3Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/`
}

export const integrationsRetrieve3 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsRetrieve3Response> => {
    return apiMutator<integrationsRetrieve3Response>(getIntegrationsRetrieve3Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type integrationsDestroy2Response204 = {
    data: void
    status: 204
}

export type integrationsDestroy2ResponseSuccess = integrationsDestroy2Response204 & {
    headers: Headers
}
export type integrationsDestroy2Response = integrationsDestroy2ResponseSuccess

export const getIntegrationsDestroy2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/`
}

export const integrationsDestroy2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsDestroy2Response> => {
    return apiMutator<integrationsDestroy2Response>(getIntegrationsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type integrationsChannelsRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsChannelsRetrieve2ResponseSuccess = integrationsChannelsRetrieve2Response200 & {
    headers: Headers
}
export type integrationsChannelsRetrieve2Response = integrationsChannelsRetrieve2ResponseSuccess

export const getIntegrationsChannelsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/channels/`
}

export const integrationsChannelsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsChannelsRetrieve2Response> => {
    return apiMutator<integrationsChannelsRetrieve2Response>(getIntegrationsChannelsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type integrationsClickupListsRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsClickupListsRetrieve2ResponseSuccess = integrationsClickupListsRetrieve2Response200 & {
    headers: Headers
}
export type integrationsClickupListsRetrieve2Response = integrationsClickupListsRetrieve2ResponseSuccess

export const getIntegrationsClickupListsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_lists/`
}

export const integrationsClickupListsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsClickupListsRetrieve2Response> => {
    return apiMutator<integrationsClickupListsRetrieve2Response>(
        getIntegrationsClickupListsRetrieve2Url(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsClickupSpacesRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsClickupSpacesRetrieve2ResponseSuccess = integrationsClickupSpacesRetrieve2Response200 & {
    headers: Headers
}
export type integrationsClickupSpacesRetrieve2Response = integrationsClickupSpacesRetrieve2ResponseSuccess

export const getIntegrationsClickupSpacesRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_spaces/`
}

export const integrationsClickupSpacesRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsClickupSpacesRetrieve2Response> => {
    return apiMutator<integrationsClickupSpacesRetrieve2Response>(
        getIntegrationsClickupSpacesRetrieve2Url(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsClickupWorkspacesRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsClickupWorkspacesRetrieve2ResponseSuccess =
    integrationsClickupWorkspacesRetrieve2Response200 & {
        headers: Headers
    }
export type integrationsClickupWorkspacesRetrieve2Response = integrationsClickupWorkspacesRetrieve2ResponseSuccess

export const getIntegrationsClickupWorkspacesRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_workspaces/`
}

export const integrationsClickupWorkspacesRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsClickupWorkspacesRetrieve2Response> => {
    return apiMutator<integrationsClickupWorkspacesRetrieve2Response>(
        getIntegrationsClickupWorkspacesRetrieve2Url(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsEmailPartialUpdate2Response200 = {
    data: IntegrationApi
    status: 200
}

export type integrationsEmailPartialUpdate2ResponseSuccess = integrationsEmailPartialUpdate2Response200 & {
    headers: Headers
}
export type integrationsEmailPartialUpdate2Response = integrationsEmailPartialUpdate2ResponseSuccess

export const getIntegrationsEmailPartialUpdate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/email/`
}

export const integrationsEmailPartialUpdate2 = async (
    projectId: string,
    id: number,
    patchedIntegrationApi: NonReadonly<PatchedIntegrationApi>,
    options?: RequestInit
): Promise<integrationsEmailPartialUpdate2Response> => {
    return apiMutator<integrationsEmailPartialUpdate2Response>(getIntegrationsEmailPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedIntegrationApi),
    })
}

export type integrationsEmailVerifyCreate2Response200 = {
    data: void
    status: 200
}

export type integrationsEmailVerifyCreate2ResponseSuccess = integrationsEmailVerifyCreate2Response200 & {
    headers: Headers
}
export type integrationsEmailVerifyCreate2Response = integrationsEmailVerifyCreate2ResponseSuccess

export const getIntegrationsEmailVerifyCreate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/email/verify/`
}

export const integrationsEmailVerifyCreate2 = async (
    projectId: string,
    id: number,
    integrationApi: NonReadonly<IntegrationApi>,
    options?: RequestInit
): Promise<integrationsEmailVerifyCreate2Response> => {
    return apiMutator<integrationsEmailVerifyCreate2Response>(getIntegrationsEmailVerifyCreate2Url(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationApi),
    })
}

export type integrationsGithubReposRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsGithubReposRetrieve2ResponseSuccess = integrationsGithubReposRetrieve2Response200 & {
    headers: Headers
}
export type integrationsGithubReposRetrieve2Response = integrationsGithubReposRetrieve2ResponseSuccess

export const getIntegrationsGithubReposRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/github_repos/`
}

export const integrationsGithubReposRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsGithubReposRetrieve2Response> => {
    return apiMutator<integrationsGithubReposRetrieve2Response>(getIntegrationsGithubReposRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type integrationsGoogleAccessibleAccountsRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsGoogleAccessibleAccountsRetrieve2ResponseSuccess =
    integrationsGoogleAccessibleAccountsRetrieve2Response200 & {
        headers: Headers
    }
export type integrationsGoogleAccessibleAccountsRetrieve2Response =
    integrationsGoogleAccessibleAccountsRetrieve2ResponseSuccess

export const getIntegrationsGoogleAccessibleAccountsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/google_accessible_accounts/`
}

export const integrationsGoogleAccessibleAccountsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsGoogleAccessibleAccountsRetrieve2Response> => {
    return apiMutator<integrationsGoogleAccessibleAccountsRetrieve2Response>(
        getIntegrationsGoogleAccessibleAccountsRetrieve2Url(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsGoogleConversionActionsRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsGoogleConversionActionsRetrieve2ResponseSuccess =
    integrationsGoogleConversionActionsRetrieve2Response200 & {
        headers: Headers
    }
export type integrationsGoogleConversionActionsRetrieve2Response =
    integrationsGoogleConversionActionsRetrieve2ResponseSuccess

export const getIntegrationsGoogleConversionActionsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/google_conversion_actions/`
}

export const integrationsGoogleConversionActionsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsGoogleConversionActionsRetrieve2Response> => {
    return apiMutator<integrationsGoogleConversionActionsRetrieve2Response>(
        getIntegrationsGoogleConversionActionsRetrieve2Url(projectId, id),
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

export type integrationsLinearTeamsRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsLinearTeamsRetrieve2ResponseSuccess = integrationsLinearTeamsRetrieve2Response200 & {
    headers: Headers
}
export type integrationsLinearTeamsRetrieve2Response = integrationsLinearTeamsRetrieve2ResponseSuccess

export const getIntegrationsLinearTeamsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linear_teams/`
}

export const integrationsLinearTeamsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsLinearTeamsRetrieve2Response> => {
    return apiMutator<integrationsLinearTeamsRetrieve2Response>(getIntegrationsLinearTeamsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type integrationsLinkedinAdsAccountsRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsLinkedinAdsAccountsRetrieve2ResponseSuccess =
    integrationsLinkedinAdsAccountsRetrieve2Response200 & {
        headers: Headers
    }
export type integrationsLinkedinAdsAccountsRetrieve2Response = integrationsLinkedinAdsAccountsRetrieve2ResponseSuccess

export const getIntegrationsLinkedinAdsAccountsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linkedin_ads_accounts/`
}

export const integrationsLinkedinAdsAccountsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsLinkedinAdsAccountsRetrieve2Response> => {
    return apiMutator<integrationsLinkedinAdsAccountsRetrieve2Response>(
        getIntegrationsLinkedinAdsAccountsRetrieve2Url(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsLinkedinAdsConversionRulesRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsLinkedinAdsConversionRulesRetrieve2ResponseSuccess =
    integrationsLinkedinAdsConversionRulesRetrieve2Response200 & {
        headers: Headers
    }
export type integrationsLinkedinAdsConversionRulesRetrieve2Response =
    integrationsLinkedinAdsConversionRulesRetrieve2ResponseSuccess

export const getIntegrationsLinkedinAdsConversionRulesRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linkedin_ads_conversion_rules/`
}

export const integrationsLinkedinAdsConversionRulesRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsLinkedinAdsConversionRulesRetrieve2Response> => {
    return apiMutator<integrationsLinkedinAdsConversionRulesRetrieve2Response>(
        getIntegrationsLinkedinAdsConversionRulesRetrieve2Url(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsTwilioPhoneNumbersRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsTwilioPhoneNumbersRetrieve2ResponseSuccess =
    integrationsTwilioPhoneNumbersRetrieve2Response200 & {
        headers: Headers
    }
export type integrationsTwilioPhoneNumbersRetrieve2Response = integrationsTwilioPhoneNumbersRetrieve2ResponseSuccess

export const getIntegrationsTwilioPhoneNumbersRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/twilio_phone_numbers/`
}

export const integrationsTwilioPhoneNumbersRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<integrationsTwilioPhoneNumbersRetrieve2Response> => {
    return apiMutator<integrationsTwilioPhoneNumbersRetrieve2Response>(
        getIntegrationsTwilioPhoneNumbersRetrieve2Url(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type integrationsAuthorizeRetrieve2Response200 = {
    data: void
    status: 200
}

export type integrationsAuthorizeRetrieve2ResponseSuccess = integrationsAuthorizeRetrieve2Response200 & {
    headers: Headers
}
export type integrationsAuthorizeRetrieve2Response = integrationsAuthorizeRetrieve2ResponseSuccess

export const getIntegrationsAuthorizeRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/authorize/`
}

export const integrationsAuthorizeRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<integrationsAuthorizeRetrieve2Response> => {
    return apiMutator<integrationsAuthorizeRetrieve2Response>(getIntegrationsAuthorizeRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export type propertyDefinitionsListResponse200 = {
    data: PaginatedEnterprisePropertyDefinitionListApi
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
    data: EnterprisePropertyDefinitionApi
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
    data: EnterprisePropertyDefinitionApi
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
    enterprisePropertyDefinitionApi: NonReadonly<EnterprisePropertyDefinitionApi>,
    options?: RequestInit
): Promise<propertyDefinitionsUpdateResponse> => {
    return apiMutator<propertyDefinitionsUpdateResponse>(getPropertyDefinitionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(enterprisePropertyDefinitionApi),
    })
}

export type propertyDefinitionsPartialUpdateResponse200 = {
    data: EnterprisePropertyDefinitionApi
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
    patchedEnterprisePropertyDefinitionApi: NonReadonly<PatchedEnterprisePropertyDefinitionApi>,
    options?: RequestInit
): Promise<propertyDefinitionsPartialUpdateResponse> => {
    return apiMutator<propertyDefinitionsPartialUpdateResponse>(getPropertyDefinitionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEnterprisePropertyDefinitionApi),
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

export type sessionRecordingsSharingList2Response200 = {
    data: SharingConfigurationApi[]
    status: 200
}

export type sessionRecordingsSharingList2ResponseSuccess = sessionRecordingsSharingList2Response200 & {
    headers: Headers
}
export type sessionRecordingsSharingList2Response = sessionRecordingsSharingList2ResponseSuccess

export const getSessionRecordingsSharingList2Url = (projectId: string, recordingId: string) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/`
}

export const sessionRecordingsSharingList2 = async (
    projectId: string,
    recordingId: string,
    options?: RequestInit
): Promise<sessionRecordingsSharingList2Response> => {
    return apiMutator<sessionRecordingsSharingList2Response>(
        getSessionRecordingsSharingList2Url(projectId, recordingId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create a new password for the sharing configuration.
 */
export type sessionRecordingsSharingPasswordsCreate2Response200 = {
    data: SharingConfigurationApi
    status: 200
}

export type sessionRecordingsSharingPasswordsCreate2ResponseSuccess =
    sessionRecordingsSharingPasswordsCreate2Response200 & {
        headers: Headers
    }
export type sessionRecordingsSharingPasswordsCreate2Response = sessionRecordingsSharingPasswordsCreate2ResponseSuccess

export const getSessionRecordingsSharingPasswordsCreate2Url = (projectId: string, recordingId: string) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/passwords/`
}

export const sessionRecordingsSharingPasswordsCreate2 = async (
    projectId: string,
    recordingId: string,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<sessionRecordingsSharingPasswordsCreate2Response> => {
    return apiMutator<sessionRecordingsSharingPasswordsCreate2Response>(
        getSessionRecordingsSharingPasswordsCreate2Url(projectId, recordingId),
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
export type sessionRecordingsSharingPasswordsDestroy2Response204 = {
    data: void
    status: 204
}

export type sessionRecordingsSharingPasswordsDestroy2ResponseSuccess =
    sessionRecordingsSharingPasswordsDestroy2Response204 & {
        headers: Headers
    }
export type sessionRecordingsSharingPasswordsDestroy2Response = sessionRecordingsSharingPasswordsDestroy2ResponseSuccess

export const getSessionRecordingsSharingPasswordsDestroy2Url = (
    projectId: string,
    recordingId: string,
    passwordId: string
) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/passwords/${passwordId}/`
}

export const sessionRecordingsSharingPasswordsDestroy2 = async (
    projectId: string,
    recordingId: string,
    passwordId: string,
    options?: RequestInit
): Promise<sessionRecordingsSharingPasswordsDestroy2Response> => {
    return apiMutator<sessionRecordingsSharingPasswordsDestroy2Response>(
        getSessionRecordingsSharingPasswordsDestroy2Url(projectId, recordingId, passwordId),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type sessionRecordingsSharingRefreshCreate2Response200 = {
    data: SharingConfigurationApi
    status: 200
}

export type sessionRecordingsSharingRefreshCreate2ResponseSuccess =
    sessionRecordingsSharingRefreshCreate2Response200 & {
        headers: Headers
    }
export type sessionRecordingsSharingRefreshCreate2Response = sessionRecordingsSharingRefreshCreate2ResponseSuccess

export const getSessionRecordingsSharingRefreshCreate2Url = (projectId: string, recordingId: string) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/refresh/`
}

export const sessionRecordingsSharingRefreshCreate2 = async (
    projectId: string,
    recordingId: string,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<sessionRecordingsSharingRefreshCreate2Response> => {
    return apiMutator<sessionRecordingsSharingRefreshCreate2Response>(
        getSessionRecordingsSharingRefreshCreate2Url(projectId, recordingId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(sharingConfigurationApi),
        }
    )
}

export type subscriptionsList2Response200 = {
    data: PaginatedSubscriptionListApi
    status: 200
}

export type subscriptionsList2ResponseSuccess = subscriptionsList2Response200 & {
    headers: Headers
}
export type subscriptionsList2Response = subscriptionsList2ResponseSuccess

export const getSubscriptionsList2Url = (projectId: string, params?: SubscriptionsList2Params) => {
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

export const subscriptionsList2 = async (
    projectId: string,
    params?: SubscriptionsList2Params,
    options?: RequestInit
): Promise<subscriptionsList2Response> => {
    return apiMutator<subscriptionsList2Response>(getSubscriptionsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type subscriptionsCreate2Response201 = {
    data: SubscriptionApi
    status: 201
}

export type subscriptionsCreate2ResponseSuccess = subscriptionsCreate2Response201 & {
    headers: Headers
}
export type subscriptionsCreate2Response = subscriptionsCreate2ResponseSuccess

export const getSubscriptionsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/subscriptions/`
}

export const subscriptionsCreate2 = async (
    projectId: string,
    subscriptionApi: NonReadonly<SubscriptionApi>,
    options?: RequestInit
): Promise<subscriptionsCreate2Response> => {
    return apiMutator<subscriptionsCreate2Response>(getSubscriptionsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionApi),
    })
}

export type subscriptionsRetrieve2Response200 = {
    data: SubscriptionApi
    status: 200
}

export type subscriptionsRetrieve2ResponseSuccess = subscriptionsRetrieve2Response200 & {
    headers: Headers
}
export type subscriptionsRetrieve2Response = subscriptionsRetrieve2ResponseSuccess

export const getSubscriptionsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<subscriptionsRetrieve2Response> => {
    return apiMutator<subscriptionsRetrieve2Response>(getSubscriptionsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type subscriptionsUpdate2Response200 = {
    data: SubscriptionApi
    status: 200
}

export type subscriptionsUpdate2ResponseSuccess = subscriptionsUpdate2Response200 & {
    headers: Headers
}
export type subscriptionsUpdate2Response = subscriptionsUpdate2ResponseSuccess

export const getSubscriptionsUpdate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsUpdate2 = async (
    projectId: string,
    id: number,
    subscriptionApi: NonReadonly<SubscriptionApi>,
    options?: RequestInit
): Promise<subscriptionsUpdate2Response> => {
    return apiMutator<subscriptionsUpdate2Response>(getSubscriptionsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionApi),
    })
}

export type subscriptionsPartialUpdate2Response200 = {
    data: SubscriptionApi
    status: 200
}

export type subscriptionsPartialUpdate2ResponseSuccess = subscriptionsPartialUpdate2Response200 & {
    headers: Headers
}
export type subscriptionsPartialUpdate2Response = subscriptionsPartialUpdate2ResponseSuccess

export const getSubscriptionsPartialUpdate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsPartialUpdate2 = async (
    projectId: string,
    id: number,
    patchedSubscriptionApi: NonReadonly<PatchedSubscriptionApi>,
    options?: RequestInit
): Promise<subscriptionsPartialUpdate2Response> => {
    return apiMutator<subscriptionsPartialUpdate2Response>(getSubscriptionsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSubscriptionApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type subscriptionsDestroy2Response405 = {
    data: void
    status: 405
}
export type subscriptionsDestroy2ResponseError = subscriptionsDestroy2Response405 & {
    headers: Headers
}

export type subscriptionsDestroy2Response = subscriptionsDestroy2ResponseError

export const getSubscriptionsDestroy2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsDestroy2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<subscriptionsDestroy2Response> => {
    return apiMutator<subscriptionsDestroy2Response>(getSubscriptionsDestroy2Url(projectId, id), {
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
