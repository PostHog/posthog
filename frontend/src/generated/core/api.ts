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
    EventDefinitionApi,
    EventDefinitionsByNameRetrieveParams,
    EventDefinitionsListParams,
    ExportedAssetApi,
    ExportsListParams,
    FileSystemApi,
    FileSystemListParams,
    FlagValueValuesRetrieve200Item,
    FlagValueValuesRetrieveParams,
    IntegrationApi,
    IntegrationsList2Params,
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
): Promise<PaginatedOrganizationDomainListApi> => {
    return apiMutator<PaginatedOrganizationDomainListApi>(getDomainsListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDomainsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/domains/`
}

export const domainsCreate = async (
    organizationId: string,
    organizationDomainApi: NonReadonly<OrganizationDomainApi>,
    options?: RequestInit
): Promise<OrganizationDomainApi> => {
    return apiMutator<OrganizationDomainApi>(getDomainsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationDomainApi),
    })
}

export const getDomainsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/`
}

export const domainsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<OrganizationDomainApi> => {
    return apiMutator<OrganizationDomainApi>(getDomainsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDomainsUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/`
}

export const domainsUpdate = async (
    organizationId: string,
    id: string,
    organizationDomainApi: NonReadonly<OrganizationDomainApi>,
    options?: RequestInit
): Promise<OrganizationDomainApi> => {
    return apiMutator<OrganizationDomainApi>(getDomainsUpdateUrl(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationDomainApi),
    })
}

export const getDomainsPartialUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/`
}

export const domainsPartialUpdate = async (
    organizationId: string,
    id: string,
    patchedOrganizationDomainApi: NonReadonly<PatchedOrganizationDomainApi>,
    options?: RequestInit
): Promise<OrganizationDomainApi> => {
    return apiMutator<OrganizationDomainApi>(getDomainsPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedOrganizationDomainApi),
    })
}

export const getDomainsDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/`
}

export const domainsDestroy = async (organizationId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDomainsDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Regenerate SCIM bearer token.
 */
export const getDomainsScimTokenCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/scim/token/`
}

export const domainsScimTokenCreate = async (
    organizationId: string,
    id: string,
    organizationDomainApi: NonReadonly<OrganizationDomainApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDomainsScimTokenCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationDomainApi),
    })
}

export const getDomainsVerifyCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/verify/`
}

export const domainsVerifyCreate = async (
    organizationId: string,
    id: string,
    organizationDomainApi: NonReadonly<OrganizationDomainApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDomainsVerifyCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationDomainApi),
    })
}

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
): Promise<PaginatedOrganizationInviteListApi> => {
    return apiMutator<PaginatedOrganizationInviteListApi>(getInvitesListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getInvitesCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/invites/`
}

export const invitesCreate = async (
    organizationId: string,
    organizationInviteApi: NonReadonly<OrganizationInviteApi>,
    options?: RequestInit
): Promise<OrganizationInviteApi> => {
    return apiMutator<OrganizationInviteApi>(getInvitesCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationInviteApi),
    })
}

export const getInvitesDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/invites/${id}/`
}

export const invitesDestroy = async (organizationId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getInvitesDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getInvitesBulkCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/invites/bulk/`
}

export const invitesBulkCreate = async (
    organizationId: string,
    organizationInviteApi: NonReadonly<OrganizationInviteApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInvitesBulkCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationInviteApi),
    })
}

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
): Promise<PaginatedOrganizationMemberListApi> => {
    return apiMutator<PaginatedOrganizationMemberListApi>(getMembersListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMembersUpdateUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/`
}

export const membersUpdate = async (
    organizationId: string,
    userUuid: string,
    organizationMemberApi: NonReadonly<OrganizationMemberApi>,
    options?: RequestInit
): Promise<OrganizationMemberApi> => {
    return apiMutator<OrganizationMemberApi>(getMembersUpdateUrl(organizationId, userUuid), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationMemberApi),
    })
}

export const getMembersPartialUpdateUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/`
}

export const membersPartialUpdate = async (
    organizationId: string,
    userUuid: string,
    patchedOrganizationMemberApi: NonReadonly<PatchedOrganizationMemberApi>,
    options?: RequestInit
): Promise<OrganizationMemberApi> => {
    return apiMutator<OrganizationMemberApi>(getMembersPartialUpdateUrl(organizationId, userUuid), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedOrganizationMemberApi),
    })
}

export const getMembersDestroyUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/`
}

export const membersDestroy = async (
    organizationId: string,
    userUuid: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMembersDestroyUrl(organizationId, userUuid), {
        ...options,
        method: 'DELETE',
    })
}

export const getMembersScopedApiKeysRetrieveUrl = (organizationId: string, userUuid: string) => {
    return `/api/organizations/${organizationId}/members/${userUuid}/scoped_api_keys/`
}

export const membersScopedApiKeysRetrieve = async (
    organizationId: string,
    userUuid: string,
    options?: RequestInit
): Promise<OrganizationMemberApi> => {
    return apiMutator<OrganizationMemberApi>(getMembersScopedApiKeysRetrieveUrl(organizationId, userUuid), {
        ...options,
        method: 'GET',
    })
}

/**
 * Projects for the current organization.
 */
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
): Promise<PaginatedProjectBackwardCompatBasicListApi> => {
    return apiMutator<PaginatedProjectBackwardCompatBasicListApi>(getList2Url(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Projects for the current organization.
 */
export const getCreate2Url = (organizationId: string) => {
    return `/api/organizations/${organizationId}/projects/`
}

export const create2 = async (
    organizationId: string,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getCreate2Url(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export const getRetrieve2Url = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

export const retrieve2 = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getRetrieve2Url(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Projects for the current organization.
 */
export const getUpdate2Url = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

export const update2 = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getUpdate2Url(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export const getPartialUpdate2Url = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

export const partialUpdate2 = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getPartialUpdate2Url(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export const getDestroy2Url = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

export const destroy2 = async (organizationId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDestroy2Url(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Projects for the current organization.
 */
export const getActivityRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/activity/`
}

export const activityRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getActivityRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Projects for the current organization.
 */
export const getAddProductIntentPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/add_product_intent/`
}

export const addProductIntentPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getAddProductIntentPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export const getChangeOrganizationCreateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/change_organization/`
}

export const changeOrganizationCreate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getChangeOrganizationCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export const getCompleteProductOnboardingPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/complete_product_onboarding/`
}

export const completeProductOnboardingPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getCompleteProductOnboardingPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export const getDeleteSecretTokenBackupPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/delete_secret_token_backup/`
}

export const deleteSecretTokenBackupPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getDeleteSecretTokenBackupPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export const getGenerateConversationsPublicTokenCreateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/generate_conversations_public_token/`
}

export const generateConversationsPublicTokenCreate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getGenerateConversationsPublicTokenCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export const getIsGeneratingDemoDataRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/is_generating_demo_data/`
}

export const isGeneratingDemoDataRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getIsGeneratingDemoDataRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Projects for the current organization.
 */
export const getResetTokenPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/reset_token/`
}

export const resetTokenPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getResetTokenPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export const getRotateSecretTokenPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/rotate_secret_token/`
}

export const rotateSecretTokenPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getRotateSecretTokenPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectBackwardCompatApi),
    })
}

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
): Promise<PaginatedRoleListApi> => {
    return apiMutator<PaginatedRoleListApi>(getRolesListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getRolesCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/roles/`
}

export const rolesCreate = async (
    organizationId: string,
    roleApi: NonReadonly<RoleApi>,
    options?: RequestInit
): Promise<RoleApi> => {
    return apiMutator<RoleApi>(getRolesCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(roleApi),
    })
}

export const getRolesRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/roles/${id}/`
}

export const rolesRetrieve = async (organizationId: string, id: string, options?: RequestInit): Promise<RoleApi> => {
    return apiMutator<RoleApi>(getRolesRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getRolesUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/roles/${id}/`
}

export const rolesUpdate = async (
    organizationId: string,
    id: string,
    roleApi: NonReadonly<RoleApi>,
    options?: RequestInit
): Promise<RoleApi> => {
    return apiMutator<RoleApi>(getRolesUpdateUrl(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(roleApi),
    })
}

export const getRolesPartialUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/roles/${id}/`
}

export const rolesPartialUpdate = async (
    organizationId: string,
    id: string,
    patchedRoleApi: NonReadonly<PatchedRoleApi>,
    options?: RequestInit
): Promise<RoleApi> => {
    return apiMutator<RoleApi>(getRolesPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedRoleApi),
    })
}

export const getRolesDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/roles/${id}/`
}

export const rolesDestroy = async (organizationId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getRolesDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
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
): Promise<PaginatedAnnotationListApi> => {
    return apiMutator<PaginatedAnnotationListApi>(getAnnotationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const getAnnotationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/annotations/`
}

export const annotationsCreate = async (
    projectId: string,
    annotationApi: NonReadonly<AnnotationApi>,
    options?: RequestInit
): Promise<AnnotationApi> => {
    return apiMutator<AnnotationApi>(getAnnotationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(annotationApi),
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const getAnnotationsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<AnnotationApi> => {
    return apiMutator<AnnotationApi>(getAnnotationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const getAnnotationsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsUpdate = async (
    projectId: string,
    id: number,
    annotationApi: NonReadonly<AnnotationApi>,
    options?: RequestInit
): Promise<AnnotationApi> => {
    return apiMutator<AnnotationApi>(getAnnotationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(annotationApi),
    })
}

/**
 * Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
 */
export const getAnnotationsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedAnnotationApi: NonReadonly<PatchedAnnotationApi>,
    options?: RequestInit
): Promise<AnnotationApi> => {
    return apiMutator<AnnotationApi>(getAnnotationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAnnotationApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getAnnotationsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/annotations/${id}/`
}

export const annotationsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getAnnotationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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
): Promise<PaginatedCommentListApi> => {
    return apiMutator<PaginatedCommentListApi>(getCommentsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCommentsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/comments/`
}

export const commentsCreate = async (
    projectId: string,
    commentApi: NonReadonly<CommentApi>,
    options?: RequestInit
): Promise<CommentApi> => {
    return apiMutator<CommentApi>(getCommentsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(commentApi),
    })
}

export const getCommentsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<CommentApi> => {
    return apiMutator<CommentApi>(getCommentsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCommentsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsUpdate = async (
    projectId: string,
    id: string,
    commentApi: NonReadonly<CommentApi>,
    options?: RequestInit
): Promise<CommentApi> => {
    return apiMutator<CommentApi>(getCommentsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(commentApi),
    })
}

export const getCommentsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCommentApi: NonReadonly<PatchedCommentApi>,
    options?: RequestInit
): Promise<CommentApi> => {
    return apiMutator<CommentApi>(getCommentsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCommentApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getCommentsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/`
}

export const commentsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getCommentsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCommentsThreadRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/comments/${id}/thread/`
}

export const commentsThreadRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getCommentsThreadRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCommentsCountRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/comments/count/`
}

export const commentsCountRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getCommentsCountRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<PaginatedDashboardTemplateListApi> => {
    return apiMutator<PaginatedDashboardTemplateListApi>(getDashboardTemplatesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardTemplatesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/dashboard_templates/`
}

export const dashboardTemplatesCreate = async (
    projectId: string,
    dashboardTemplateApi: NonReadonly<DashboardTemplateApi>,
    options?: RequestInit
): Promise<DashboardTemplateApi> => {
    return apiMutator<DashboardTemplateApi>(getDashboardTemplatesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardTemplateApi),
    })
}

export const getDashboardTemplatesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

export const dashboardTemplatesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DashboardTemplateApi> => {
    return apiMutator<DashboardTemplateApi>(getDashboardTemplatesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardTemplatesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

export const dashboardTemplatesUpdate = async (
    projectId: string,
    id: string,
    dashboardTemplateApi: NonReadonly<DashboardTemplateApi>,
    options?: RequestInit
): Promise<DashboardTemplateApi> => {
    return apiMutator<DashboardTemplateApi>(getDashboardTemplatesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dashboardTemplateApi),
    })
}

export const getDashboardTemplatesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

export const dashboardTemplatesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDashboardTemplateApi: NonReadonly<PatchedDashboardTemplateApi>,
    options?: RequestInit
): Promise<DashboardTemplateApi> => {
    return apiMutator<DashboardTemplateApi>(getDashboardTemplatesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDashboardTemplateApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getDashboardTemplatesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dashboard_templates/${id}/`
}

export const dashboardTemplatesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getDashboardTemplatesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDashboardTemplatesJsonSchemaRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/dashboard_templates/json_schema/`
}

export const dashboardTemplatesJsonSchemaRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDashboardTemplatesJsonSchemaRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<PaginatedEnterpriseEventDefinitionListApi> => {
    return apiMutator<PaginatedEnterpriseEventDefinitionListApi>(getEventDefinitionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEventDefinitionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/`
}

export const eventDefinitionsCreate = async (
    projectId: string,
    enterpriseEventDefinitionApi: NonReadonly<EnterpriseEventDefinitionApi>,
    options?: RequestInit
): Promise<EnterpriseEventDefinitionApi> => {
    return apiMutator<EnterpriseEventDefinitionApi>(getEventDefinitionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(enterpriseEventDefinitionApi),
    })
}

export const getEventDefinitionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<EnterpriseEventDefinitionApi> => {
    return apiMutator<EnterpriseEventDefinitionApi>(getEventDefinitionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getEventDefinitionsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsUpdate = async (
    projectId: string,
    id: string,
    enterpriseEventDefinitionApi: NonReadonly<EnterpriseEventDefinitionApi>,
    options?: RequestInit
): Promise<EnterpriseEventDefinitionApi> => {
    return apiMutator<EnterpriseEventDefinitionApi>(getEventDefinitionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(enterpriseEventDefinitionApi),
    })
}

export const getEventDefinitionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedEnterpriseEventDefinitionApi: NonReadonly<PatchedEnterpriseEventDefinitionApi>,
    options?: RequestInit
): Promise<EnterpriseEventDefinitionApi> => {
    return apiMutator<EnterpriseEventDefinitionApi>(getEventDefinitionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEnterpriseEventDefinitionApi),
    })
}

export const getEventDefinitionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEventDefinitionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEventDefinitionsMetricsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/metrics/`
}

export const eventDefinitionsMetricsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEventDefinitionsMetricsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get event definition by exact name
 */
export const getEventDefinitionsByNameRetrieveUrl = (
    projectId: string,
    params: EventDefinitionsByNameRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/event_definitions/by_name/?${stringifiedParams}`
        : `/api/projects/${projectId}/event_definitions/by_name/`
}

export const eventDefinitionsByNameRetrieve = async (
    projectId: string,
    params: EventDefinitionsByNameRetrieveParams,
    options?: RequestInit
): Promise<EventDefinitionApi> => {
    return apiMutator<EventDefinitionApi>(getEventDefinitionsByNameRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEventDefinitionsGolangRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/golang/`
}

export const eventDefinitionsGolangRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEventDefinitionsGolangRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEventDefinitionsPythonRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/python/`
}

export const eventDefinitionsPythonRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEventDefinitionsPythonRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEventDefinitionsTypescriptRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/typescript/`
}

export const eventDefinitionsTypescriptRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEventDefinitionsTypescriptRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<PaginatedExportedAssetListApi> => {
    return apiMutator<PaginatedExportedAssetListApi>(getExportsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getExportsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/exports/`
}

export const exportsCreate = async (
    projectId: string,
    exportedAssetApi: NonReadonly<ExportedAssetApi>,
    options?: RequestInit
): Promise<ExportedAssetApi> => {
    return apiMutator<ExportedAssetApi>(getExportsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(exportedAssetApi),
    })
}

export const getExportsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/exports/${id}/`
}

export const exportsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ExportedAssetApi> => {
    return apiMutator<ExportedAssetApi>(getExportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getExportsContentRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/exports/${id}/content/`
}

export const exportsContentRetrieve = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getExportsContentRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<PaginatedFileSystemListApi> => {
    return apiMutator<PaginatedFileSystemListApi>(getFileSystemListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getFileSystemCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/`
}

export const fileSystemCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<FileSystemApi> => {
    return apiMutator<FileSystemApi>(getFileSystemCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getFileSystemRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<FileSystemApi> => {
    return apiMutator<FileSystemApi>(getFileSystemRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getFileSystemUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemUpdate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<FileSystemApi> => {
    return apiMutator<FileSystemApi>(getFileSystemUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getFileSystemPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemPartialUpdate = async (
    projectId: string,
    id: string,
    patchedFileSystemApi: NonReadonly<PatchedFileSystemApi>,
    options?: RequestInit
): Promise<FileSystemApi> => {
    return apiMutator<FileSystemApi>(getFileSystemPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFileSystemApi),
    })
}

export const getFileSystemDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/`
}

export const fileSystemDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFileSystemDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Get count of all files in a folder.
 */
export const getFileSystemCountCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/count/`
}

export const fileSystemCountCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFileSystemCountCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getFileSystemLinkCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/link/`
}

export const fileSystemLinkCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFileSystemLinkCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getFileSystemMoveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/move/`
}

export const fileSystemMoveCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFileSystemMoveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

/**
 * Get count of all files in a folder.
 */
export const getFileSystemCountByPathCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/count_by_path/`
}

export const fileSystemCountByPathCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFileSystemCountByPathCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getFileSystemLogViewRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/log_view/`
}

export const fileSystemLogViewRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFileSystemLogViewRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getFileSystemLogViewCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/log_view/`
}

export const fileSystemLogViewCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFileSystemLogViewCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getFileSystemUndoDeleteCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/undo_delete/`
}

export const fileSystemUndoDeleteCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFileSystemUndoDeleteCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getFileSystemUnfiledRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/unfiled/`
}

export const fileSystemUnfiledRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFileSystemUnfiledRetrieveUrl(projectId), {
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
): Promise<FlagValueValuesRetrieve200Item[]> => {
    return apiMutator<FlagValueValuesRetrieve200Item[]>(getFlagValueValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getInsightsSharingListUrl = (projectId: string, insightId: number) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/`
}

export const insightsSharingList = async (
    projectId: string,
    insightId: number,
    options?: RequestInit
): Promise<SharingConfigurationApi[]> => {
    return apiMutator<SharingConfigurationApi[]>(getInsightsSharingListUrl(projectId, insightId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new password for the sharing configuration.
 */
export const getInsightsSharingPasswordsCreateUrl = (projectId: string, insightId: number) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/passwords/`
}

export const insightsSharingPasswordsCreate = async (
    projectId: string,
    insightId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getInsightsSharingPasswordsCreateUrl(projectId, insightId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

/**
 * Delete a password from the sharing configuration.
 */
export const getInsightsSharingPasswordsDestroyUrl = (projectId: string, insightId: number, passwordId: string) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/passwords/${passwordId}/`
}

export const insightsSharingPasswordsDestroy = async (
    projectId: string,
    insightId: number,
    passwordId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getInsightsSharingPasswordsDestroyUrl(projectId, insightId, passwordId), {
        ...options,
        method: 'DELETE',
    })
}

export const getInsightsSharingRefreshCreateUrl = (projectId: string, insightId: number) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/refresh/`
}

export const insightsSharingRefreshCreate = async (
    projectId: string,
    insightId: number,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getInsightsSharingRefreshCreateUrl(projectId, insightId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

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
): Promise<PaginatedIntegrationListApi> => {
    return apiMutator<PaginatedIntegrationListApi>(getIntegrationsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/`
}

export const integrationsCreate = async (
    projectId: string,
    integrationApi: NonReadonly<IntegrationApi>,
    options?: RequestInit
): Promise<IntegrationApi> => {
    return apiMutator<IntegrationApi>(getIntegrationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationApi),
    })
}

export const getIntegrationsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/`
}

export const integrationsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<IntegrationApi> => {
    return apiMutator<IntegrationApi>(getIntegrationsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/`
}

export const integrationsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getIntegrationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getIntegrationsChannelsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/channels/`
}

export const integrationsChannelsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsChannelsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsClickupListsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_lists/`
}

export const integrationsClickupListsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsClickupListsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsClickupSpacesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_spaces/`
}

export const integrationsClickupSpacesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsClickupSpacesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsClickupWorkspacesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/clickup_workspaces/`
}

export const integrationsClickupWorkspacesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsClickupWorkspacesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsEmailPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/email/`
}

export const integrationsEmailPartialUpdate = async (
    projectId: string,
    id: number,
    patchedIntegrationApi: NonReadonly<PatchedIntegrationApi>,
    options?: RequestInit
): Promise<IntegrationApi> => {
    return apiMutator<IntegrationApi>(getIntegrationsEmailPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedIntegrationApi),
    })
}

export const getIntegrationsEmailVerifyCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/email/verify/`
}

export const integrationsEmailVerifyCreate = async (
    projectId: string,
    id: number,
    integrationApi: NonReadonly<IntegrationApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsEmailVerifyCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(integrationApi),
    })
}

export const getIntegrationsGithubReposRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/github_repos/`
}

export const integrationsGithubReposRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsGithubReposRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsGoogleAccessibleAccountsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/google_accessible_accounts/`
}

export const integrationsGoogleAccessibleAccountsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsGoogleAccessibleAccountsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsGoogleConversionActionsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/google_conversion_actions/`
}

export const integrationsGoogleConversionActionsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsGoogleConversionActionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsJiraProjectsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/jira_projects/`
}

export const integrationsJiraProjectsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsJiraProjectsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsLinearTeamsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linear_teams/`
}

export const integrationsLinearTeamsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsLinearTeamsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsLinkedinAdsAccountsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linkedin_ads_accounts/`
}

export const integrationsLinkedinAdsAccountsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsLinkedinAdsAccountsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsLinkedinAdsConversionRulesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/linkedin_ads_conversion_rules/`
}

export const integrationsLinkedinAdsConversionRulesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsLinkedinAdsConversionRulesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsTwilioPhoneNumbersRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/integrations/${id}/twilio_phone_numbers/`
}

export const integrationsTwilioPhoneNumbersRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIntegrationsTwilioPhoneNumbersRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIntegrationsAuthorizeRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/integrations/authorize/`
}

export const integrationsAuthorizeRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getIntegrationsAuthorizeRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<PaginatedEnterprisePropertyDefinitionListApi> => {
    return apiMutator<PaginatedEnterprisePropertyDefinitionListApi>(getPropertyDefinitionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPropertyDefinitionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/property_definitions/${id}/`
}

export const propertyDefinitionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<EnterprisePropertyDefinitionApi> => {
    return apiMutator<EnterprisePropertyDefinitionApi>(getPropertyDefinitionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getPropertyDefinitionsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/property_definitions/${id}/`
}

export const propertyDefinitionsUpdate = async (
    projectId: string,
    id: string,
    enterprisePropertyDefinitionApi: NonReadonly<EnterprisePropertyDefinitionApi>,
    options?: RequestInit
): Promise<EnterprisePropertyDefinitionApi> => {
    return apiMutator<EnterprisePropertyDefinitionApi>(getPropertyDefinitionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(enterprisePropertyDefinitionApi),
    })
}

export const getPropertyDefinitionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/property_definitions/${id}/`
}

export const propertyDefinitionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedEnterprisePropertyDefinitionApi: NonReadonly<PatchedEnterprisePropertyDefinitionApi>,
    options?: RequestInit
): Promise<EnterprisePropertyDefinitionApi> => {
    return apiMutator<EnterprisePropertyDefinitionApi>(getPropertyDefinitionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEnterprisePropertyDefinitionApi),
    })
}

export const getPropertyDefinitionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/property_definitions/${id}/`
}

export const propertyDefinitionsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPropertyDefinitionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Allows a caller to provide a list of event names and a single property name
Returns a map of the event names to a boolean representing whether that property has ever been seen with that event_name
 */
export const getPropertyDefinitionsSeenTogetherRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/property_definitions/seen_together/`
}

export const propertyDefinitionsSeenTogetherRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPropertyDefinitionsSeenTogetherRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
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
): Promise<PaginatedScheduledChangeListApi> => {
    return apiMutator<PaginatedScheduledChangeListApi>(getScheduledChangesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const getScheduledChangesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/scheduled_changes/`
}

export const scheduledChangesCreate = async (
    projectId: string,
    scheduledChangeApi: NonReadonly<ScheduledChangeApi>,
    options?: RequestInit
): Promise<ScheduledChangeApi> => {
    return apiMutator<ScheduledChangeApi>(getScheduledChangesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(scheduledChangeApi),
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const getScheduledChangesRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<ScheduledChangeApi> => {
    return apiMutator<ScheduledChangeApi>(getScheduledChangesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const getScheduledChangesUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesUpdate = async (
    projectId: string,
    id: number,
    scheduledChangeApi: NonReadonly<ScheduledChangeApi>,
    options?: RequestInit
): Promise<ScheduledChangeApi> => {
    return apiMutator<ScheduledChangeApi>(getScheduledChangesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(scheduledChangeApi),
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const getScheduledChangesPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesPartialUpdate = async (
    projectId: string,
    id: number,
    patchedScheduledChangeApi: NonReadonly<PatchedScheduledChangeApi>,
    options?: RequestInit
): Promise<ScheduledChangeApi> => {
    return apiMutator<ScheduledChangeApi>(getScheduledChangesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedScheduledChangeApi),
    })
}

/**
 * Create, read, update and delete scheduled changes.
 */
export const getScheduledChangesDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/scheduled_changes/${id}/`
}

export const scheduledChangesDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getScheduledChangesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getSessionRecordingsSharingListUrl = (projectId: string, recordingId: string) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/`
}

export const sessionRecordingsSharingList = async (
    projectId: string,
    recordingId: string,
    options?: RequestInit
): Promise<SharingConfigurationApi[]> => {
    return apiMutator<SharingConfigurationApi[]>(getSessionRecordingsSharingListUrl(projectId, recordingId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new password for the sharing configuration.
 */
export const getSessionRecordingsSharingPasswordsCreateUrl = (projectId: string, recordingId: string) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/passwords/`
}

export const sessionRecordingsSharingPasswordsCreate = async (
    projectId: string,
    recordingId: string,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getSessionRecordingsSharingPasswordsCreateUrl(projectId, recordingId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

/**
 * Delete a password from the sharing configuration.
 */
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
): Promise<void> => {
    return apiMutator<void>(getSessionRecordingsSharingPasswordsDestroyUrl(projectId, recordingId, passwordId), {
        ...options,
        method: 'DELETE',
    })
}

export const getSessionRecordingsSharingRefreshCreateUrl = (projectId: string, recordingId: string) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/refresh/`
}

export const sessionRecordingsSharingRefreshCreate = async (
    projectId: string,
    recordingId: string,
    sharingConfigurationApi: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getSessionRecordingsSharingRefreshCreateUrl(projectId, recordingId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

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
): Promise<PaginatedSubscriptionListApi> => {
    return apiMutator<PaginatedSubscriptionListApi>(getSubscriptionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getSubscriptionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/subscriptions/`
}

export const subscriptionsCreate = async (
    projectId: string,
    subscriptionApi: NonReadonly<SubscriptionApi>,
    options?: RequestInit
): Promise<SubscriptionApi> => {
    return apiMutator<SubscriptionApi>(getSubscriptionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionApi),
    })
}

export const getSubscriptionsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<SubscriptionApi> => {
    return apiMutator<SubscriptionApi>(getSubscriptionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSubscriptionsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsUpdate = async (
    projectId: string,
    id: number,
    subscriptionApi: NonReadonly<SubscriptionApi>,
    options?: RequestInit
): Promise<SubscriptionApi> => {
    return apiMutator<SubscriptionApi>(getSubscriptionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(subscriptionApi),
    })
}

export const getSubscriptionsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedSubscriptionApi: NonReadonly<PatchedSubscriptionApi>,
    options?: RequestInit
): Promise<SubscriptionApi> => {
    return apiMutator<SubscriptionApi>(getSubscriptionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSubscriptionApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getSubscriptionsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/`
}

export const subscriptionsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getSubscriptionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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

export const usersList = async (params?: UsersListParams, options?: RequestInit): Promise<PaginatedUserListApi> => {
    return apiMutator<PaginatedUserListApi>(getUsersListUrl(params), {
        ...options,
        method: 'GET',
    })
}

export const getUsersRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/`
}

export const usersRetrieve = async (uuid: string, options?: RequestInit): Promise<UserApi> => {
    return apiMutator<UserApi>(getUsersRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

export const getUsersUpdateUrl = (uuid: string) => {
    return `/api/users/${uuid}/`
}

export const usersUpdate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<UserApi> => {
    return apiMutator<UserApi>(getUsersUpdateUrl(uuid), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export const getUsersPartialUpdateUrl = (uuid: string) => {
    return `/api/users/${uuid}/`
}

export const usersPartialUpdate = async (
    uuid: string,
    patchedUserApi: NonReadonly<PatchedUserApi>,
    options?: RequestInit
): Promise<UserApi> => {
    return apiMutator<UserApi>(getUsersPartialUpdateUrl(uuid), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUserApi),
    })
}

export const getUsersDestroyUrl = (uuid: string) => {
    return `/api/users/${uuid}/`
}

export const usersDestroy = async (uuid: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUsersDestroyUrl(uuid), {
        ...options,
        method: 'DELETE',
    })
}

export const getUsersHedgehogConfigRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/hedgehog_config/`
}

export const usersHedgehogConfigRetrieve = async (uuid: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUsersHedgehogConfigRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

export const getUsersHedgehogConfigPartialUpdateUrl = (uuid: string) => {
    return `/api/users/${uuid}/hedgehog_config/`
}

export const usersHedgehogConfigPartialUpdate = async (
    uuid: string,
    patchedUserApi: NonReadonly<PatchedUserApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersHedgehogConfigPartialUpdateUrl(uuid), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUserApi),
    })
}

export const getUsersScenePersonalisationCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/scene_personalisation/`
}

export const usersScenePersonalisationCreate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersScenePersonalisationCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export const getUsersStart2faSetupRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/start_2fa_setup/`
}

export const usersStart2faSetupRetrieve = async (uuid: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUsersStart2faSetupRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

/**
 * Generate new backup codes, invalidating any existing ones
 */
export const getUsersTwoFactorBackupCodesCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_backup_codes/`
}

export const usersTwoFactorBackupCodesCreate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersTwoFactorBackupCodesCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

/**
 * Disable 2FA and remove all related devices
 */
export const getUsersTwoFactorDisableCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_disable/`
}

export const usersTwoFactorDisableCreate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersTwoFactorDisableCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export const getUsersTwoFactorStartSetupRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_start_setup/`
}

export const usersTwoFactorStartSetupRetrieve = async (uuid: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUsersTwoFactorStartSetupRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get current 2FA status including backup codes if enabled
 */
export const getUsersTwoFactorStatusRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_status/`
}

export const usersTwoFactorStatusRetrieve = async (uuid: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUsersTwoFactorStatusRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

export const getUsersTwoFactorValidateCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_validate/`
}

export const usersTwoFactorValidateCreate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersTwoFactorValidateCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export const getUsersValidate2faCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/validate_2fa/`
}

export const usersValidate2faCreate = async (
    uuid: string,
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersValidate2faCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export const getUsersCancelEmailChangeRequestPartialUpdateUrl = () => {
    return `/api/users/cancel_email_change_request/`
}

export const usersCancelEmailChangeRequestPartialUpdate = async (
    patchedUserApi: NonReadonly<PatchedUserApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersCancelEmailChangeRequestPartialUpdateUrl(), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUserApi),
    })
}

export const getUsersRequestEmailVerificationCreateUrl = () => {
    return `/api/users/request_email_verification/`
}

export const usersRequestEmailVerificationCreate = async (
    userApi: NonReadonly<UserApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersRequestEmailVerificationCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}

export const getUsersVerifyEmailCreateUrl = () => {
    return `/api/users/verify_email/`
}

export const usersVerifyEmailCreate = async (userApi: NonReadonly<UserApi>, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUsersVerifyEmailCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userApi),
    })
}
