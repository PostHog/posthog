import { apiMutator } from '../../lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - core
 * OpenAPI spec version: 1.0.0
 */
import type {
    BulkUpdateTagsRequestApi,
    BulkUpdateTagsResponseApi,
    CIMDVerificationTokenApi,
    CIMDVerificationTokenWithValueApi,
    CimdVerificationTokensListParams,
    ContextGenerationApi,
    ContextGenerationSetApi,
    DesktopFileSystemInstructionsVersionsListParams,
    DesktopFileSystemListParams,
    DesktopFileSystemShortcutListParams,
    DomainsListParams,
    EnterprisePropertyDefinitionApi,
    ExportedAssetApi,
    ExportsListParams,
    FileSystemApi,
    FileSystemListParams,
    FileSystemShortcutApi,
    FileSystemShortcutListParams,
    FileSystemShortcutReorderApi,
    FolderInstructionsApi,
    FolderInstructionsPublishApi,
    GitHubBranchesResponseApi,
    GitHubReposRefreshResponseApi,
    GitHubReposResponseApi,
    IdentityProviderConfigApi,
    IdentityProviderConfigsListParams,
    InvitesListParams,
    OauthApplicationsListParams,
    OnboardingSkipRequestApi,
    OrganizationDomainApi,
    OrganizationInviteApi,
    OrganizationInviteDelegateApi,
    OrganizationsProjectsListParams,
    PaginatedCIMDVerificationTokenListApi,
    PaginatedEnterprisePropertyDefinitionListApi,
    PaginatedExportedAssetListApi,
    PaginatedFileSystemListApi,
    PaginatedFileSystemShortcutListApi,
    PaginatedFolderInstructionsVersionListApi,
    PaginatedIdentityProviderConfigListApi,
    PaginatedOrganizationDomainListApi,
    PaginatedOrganizationInviteListApi,
    PaginatedOrganizationOAuthApplicationListApi,
    PaginatedProjectBackwardCompatBasicListApi,
    PaginatedProjectSecretAPIKeyListApi,
    PaginatedUserGitHubIntegrationListResponseListApi,
    PaginatedUserListApi,
    PatchedCanvasPublishApi,
    PatchedEnterprisePropertyDefinitionApi,
    PatchedFileSystemApi,
    PatchedFileSystemShortcutApi,
    PatchedFolderInstructionsPublishApi,
    PatchedIdentityProviderConfigApi,
    PatchedOrganizationDomainApi,
    PatchedProjectBackwardCompatApi,
    PatchedProjectSecretAPIKeyApi,
    PatchedUserApi,
    ProductEnablementApi,
    ProductEnablementResultApi,
    ProjectBackwardCompatApi,
    ProjectSecretAPIKeyApi,
    ProjectSecretApiKeysListParams,
    PropertyDefinitionsListParams,
    RevokeOtherSessionsResponseApi,
    SCIMTokenResponseApi,
    SharingConfigurationApi,
    UserApi,
    UserAuthSessionApi,
    UserGitHubLinkStartRequestApi,
    UserGitHubLinkStartResponseApi,
    UserGitHubPrepareCallbackRequestApi,
    UserPushTokenItemApi,
    UserPushTokenRegisterRequestApi,
    UserPushTokenUnregisterRequestApi,
    UserSlackLinkStartRequestApi,
    UserSlackLinkStartResponseApi,
    UserSlackLinkableWorkspaceListResponseApi,
    UsersIntegrationsGithubBranchesRetrieveParams,
    UsersIntegrationsGithubReposRetrieveParams,
    UsersIntegrationsListParams,
    UsersListParams,
    UsersLoginSessionsListParams,
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

export const getCimdVerificationTokensListUrl = (organizationId: string, params?: CimdVerificationTokensListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/cimd_verification_tokens/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/cimd_verification_tokens/`
}

/**
 * Manage CIMD verification tokens for an organization.
 *
 * A partner embeds the plaintext token in their CIMD metadata document as
 * `verification_token` inside the `com.posthog` object (the legacy top-level
 * `posthog_verification_token` field still works as a fallback). When PostHog fetches
 * the metadata, matching the token links the partner app to this organization and
 * grants a higher default rate limit for account provisioning.
 *
 * The plaintext value is only available on creation; we store a hash.
 */
export const cimdVerificationTokensList = async (
    organizationId: string,
    params?: CimdVerificationTokensListParams,
    options?: RequestInit
): Promise<PaginatedCIMDVerificationTokenListApi> => {
    return apiMutator<PaginatedCIMDVerificationTokenListApi>(getCimdVerificationTokensListUrl(organizationId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCimdVerificationTokensCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/cimd_verification_tokens/`
}

/**
 * Manage CIMD verification tokens for an organization.
 *
 * A partner embeds the plaintext token in their CIMD metadata document as
 * `verification_token` inside the `com.posthog` object (the legacy top-level
 * `posthog_verification_token` field still works as a fallback). When PostHog fetches
 * the metadata, matching the token links the partner app to this organization and
 * grants a higher default rate limit for account provisioning.
 *
 * The plaintext value is only available on creation; we store a hash.
 */
export const cimdVerificationTokensCreate = async (
    organizationId: string,
    cIMDVerificationTokenApi: NonReadonly<CIMDVerificationTokenApi>,
    options?: RequestInit
): Promise<CIMDVerificationTokenWithValueApi> => {
    return apiMutator<CIMDVerificationTokenWithValueApi>(getCimdVerificationTokensCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(cIMDVerificationTokenApi),
    })
}

export const getCimdVerificationTokensRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/cimd_verification_tokens/${id}/`
}

/**
 * Manage CIMD verification tokens for an organization.
 *
 * A partner embeds the plaintext token in their CIMD metadata document as
 * `verification_token` inside the `com.posthog` object (the legacy top-level
 * `posthog_verification_token` field still works as a fallback). When PostHog fetches
 * the metadata, matching the token links the partner app to this organization and
 * grants a higher default rate limit for account provisioning.
 *
 * The plaintext value is only available on creation; we store a hash.
 */
export const cimdVerificationTokensRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<CIMDVerificationTokenApi> => {
    return apiMutator<CIMDVerificationTokenApi>(getCimdVerificationTokensRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCimdVerificationTokensDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/cimd_verification_tokens/${id}/`
}

/**
 * Manage CIMD verification tokens for an organization.
 *
 * A partner embeds the plaintext token in their CIMD metadata document as
 * `verification_token` inside the `com.posthog` object (the legacy top-level
 * `posthog_verification_token` field still works as a fallback). When PostHog fetches
 * the metadata, matching the token links the partner app to this organization and
 * grants a higher default rate limit for account provisioning.
 *
 * The plaintext value is only available on creation; we store a hash.
 */
export const cimdVerificationTokensDestroy = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCimdVerificationTokensDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDomainsListUrl = (organizationId: string, params?: DomainsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
    patchedOrganizationDomainApi?: NonReadonly<PatchedOrganizationDomainApi>,
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

export const getDomainsScimLogsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/scim/logs/`
}

export const domainsScimLogsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDomainsScimLogsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDomainsScimTokenCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/scim/token/`
}

/**
 * Regenerate SCIM bearer token.
 */
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

export const getIdentityProviderConfigsListUrl = (
    organizationId: string,
    params?: IdentityProviderConfigsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/identity_provider_configs/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/identity_provider_configs/`
}

export const identityProviderConfigsList = async (
    organizationId: string,
    params?: IdentityProviderConfigsListParams,
    options?: RequestInit
): Promise<PaginatedIdentityProviderConfigListApi> => {
    return apiMutator<PaginatedIdentityProviderConfigListApi>(
        getIdentityProviderConfigsListUrl(organizationId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getIdentityProviderConfigsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/identity_provider_configs/`
}

export const identityProviderConfigsCreate = async (
    organizationId: string,
    identityProviderConfigApi?: NonReadonly<IdentityProviderConfigApi>,
    options?: RequestInit
): Promise<IdentityProviderConfigApi> => {
    return apiMutator<IdentityProviderConfigApi>(getIdentityProviderConfigsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(identityProviderConfigApi),
    })
}

export const getIdentityProviderConfigsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/identity_provider_configs/${id}/`
}

export const identityProviderConfigsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<IdentityProviderConfigApi> => {
    return apiMutator<IdentityProviderConfigApi>(getIdentityProviderConfigsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getIdentityProviderConfigsUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/identity_provider_configs/${id}/`
}

export const identityProviderConfigsUpdate = async (
    organizationId: string,
    id: string,
    identityProviderConfigApi?: NonReadonly<IdentityProviderConfigApi>,
    options?: RequestInit
): Promise<IdentityProviderConfigApi> => {
    return apiMutator<IdentityProviderConfigApi>(getIdentityProviderConfigsUpdateUrl(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(identityProviderConfigApi),
    })
}

export const getIdentityProviderConfigsPartialUpdateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/identity_provider_configs/${id}/`
}

export const identityProviderConfigsPartialUpdate = async (
    organizationId: string,
    id: string,
    patchedIdentityProviderConfigApi?: NonReadonly<PatchedIdentityProviderConfigApi>,
    options?: RequestInit
): Promise<IdentityProviderConfigApi> => {
    return apiMutator<IdentityProviderConfigApi>(getIdentityProviderConfigsPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedIdentityProviderConfigApi),
    })
}

export const getIdentityProviderConfigsDestroyUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/identity_provider_configs/${id}/`
}

export const identityProviderConfigsDestroy = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getIdentityProviderConfigsDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getIdentityProviderConfigsScimTokenCreateUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/identity_provider_configs/${id}/scim/token/`
}

/**
 * Regenerate the SCIM bearer token for this IdP config.
 */
export const identityProviderConfigsScimTokenCreate = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<SCIMTokenResponseApi> => {
    return apiMutator<SCIMTokenResponseApi>(getIdentityProviderConfigsScimTokenCreateUrl(organizationId, id), {
        ...options,
        method: 'POST',
    })
}

export const getInvitesListUrl = (organizationId: string, params?: InvitesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
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

export const getInvitesDelegateCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/invites/delegate/`
}

/**
 * Create an onboarding delegation invite: an admin-level invite flagged as a setup delegation.
 * Sends a single dedicated delegation email and records the inviting user as having delegated.
 */
export const invitesDelegateCreate = async (
    organizationId: string,
    organizationInviteDelegateApi: OrganizationInviteDelegateApi,
    options?: RequestInit
): Promise<OrganizationInviteApi> => {
    return apiMutator<OrganizationInviteApi>(getInvitesDelegateCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(organizationInviteDelegateApi),
    })
}

export const getOauthApplicationsListUrl = (organizationId: string, params?: OauthApplicationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/oauth_applications/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/oauth_applications/`
}

/**
 * ViewSet for listing OAuth applications at the organization level (read-only).
 */
export const oauthApplicationsList = async (
    organizationId: string,
    params?: OauthApplicationsListParams,
    options?: RequestInit
): Promise<PaginatedOrganizationOAuthApplicationListApi> => {
    return apiMutator<PaginatedOrganizationOAuthApplicationListApi>(
        getOauthApplicationsListUrl(organizationId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsListUrl = (organizationId: string, params?: OrganizationsProjectsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/projects/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/projects/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsList = async (
    organizationId: string,
    params?: OrganizationsProjectsListParams,
    options?: RequestInit
): Promise<PaginatedProjectBackwardCompatBasicListApi> => {
    return apiMutator<PaginatedProjectBackwardCompatBasicListApi>(
        getOrganizationsProjectsListUrl(organizationId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/projects/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsCreate = async (
    organizationId: string,
    projectBackwardCompatApi?: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getOrganizationsProjectsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectBackwardCompatApi),
    })
}

export const getOrganizationsProjectsRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

/**
 * Retrieve a project and its settings.
 */
export const organizationsProjectsRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getOrganizationsProjectsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getOrganizationsProjectsUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

/**
 * Replace a project and its settings. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
export const organizationsProjectsUpdate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi?: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getOrganizationsProjectsUpdateUrl(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectBackwardCompatApi),
    })
}

export const getOrganizationsProjectsPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

/**
 * Update one or more of a project's settings. Only the fields included in the request body are changed.
 */
export const organizationsProjectsPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi?: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getOrganizationsProjectsPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectBackwardCompatApi),
    })
}

export const getOrganizationsProjectsDestroyUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsDestroy = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getOrganizationsProjectsDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getOrganizationsProjectsActivityRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/activity/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsActivityRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getOrganizationsProjectsActivityRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getOrganizationsProjectsAddProductIntentPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/add_product_intent/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsAddProductIntentPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi?: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsAddProductIntentPartialUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedProjectBackwardCompatApi),
        }
    )
}

export const getOrganizationsProjectsChangeOrganizationCreateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/change_organization/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsChangeOrganizationCreate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi?: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsChangeOrganizationCreateUrl(organizationId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(projectBackwardCompatApi),
        }
    )
}

export const getOrganizationsProjectsCompleteProductOnboardingPartialUpdateUrl = (
    organizationId: string,
    id: number
) => {
    return `/api/organizations/${organizationId}/projects/${id}/complete_product_onboarding/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsCompleteProductOnboardingPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi?: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsCompleteProductOnboardingPartialUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedProjectBackwardCompatApi),
        }
    )
}

export const getOrganizationsProjectsDefaultEvaluationContextsRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/default_evaluation_contexts/`
}

/**
 * Manage default evaluation contexts for a project.
 */
export const organizationsProjectsDefaultEvaluationContextsRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsDefaultEvaluationContextsRetrieveUrl(organizationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsDefaultEvaluationContextsCreateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/default_evaluation_contexts/`
}

/**
 * Manage default evaluation contexts for a project.
 */
export const organizationsProjectsDefaultEvaluationContextsCreate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi?: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsDefaultEvaluationContextsCreateUrl(organizationId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(projectBackwardCompatApi),
        }
    )
}

export const getOrganizationsProjectsDefaultEvaluationContextsDestroyUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/default_evaluation_contexts/`
}

/**
 * Manage default evaluation contexts for a project.
 */
export const organizationsProjectsDefaultEvaluationContextsDestroy = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getOrganizationsProjectsDefaultEvaluationContextsDestroyUrl(organizationId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getOrganizationsProjectsDefaultReleaseConditionsRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/default_release_conditions/`
}

/**
 * Manage default release conditions for new feature flags in this project.
 */
export const organizationsProjectsDefaultReleaseConditionsRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsDefaultReleaseConditionsRetrieveUrl(organizationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsDefaultReleaseConditionsUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/default_release_conditions/`
}

/**
 * Manage default release conditions for new feature flags in this project.
 */
export const organizationsProjectsDefaultReleaseConditionsUpdate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi?: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsDefaultReleaseConditionsUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(projectBackwardCompatApi),
        }
    )
}

export const getOrganizationsProjectsDeleteSecretTokenBackupPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/delete_secret_token_backup/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsDeleteSecretTokenBackupPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi?: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsDeleteSecretTokenBackupPartialUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedProjectBackwardCompatApi),
        }
    )
}

export const getOrganizationsProjectsEventIngestionRestrictionsRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/event_ingestion_restrictions/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsEventIngestionRestrictionsRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsEventIngestionRestrictionsRetrieveUrl(organizationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsExperimentsConfigRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/experiments_config/`
}

/**
 * Manage experiment configuration for this project.
 */
export const organizationsProjectsExperimentsConfigRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsExperimentsConfigRetrieveUrl(organizationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsExperimentsConfigPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/experiments_config/`
}

/**
 * Manage experiment configuration for this project.
 */
export const organizationsProjectsExperimentsConfigPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi?: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsExperimentsConfigPartialUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedProjectBackwardCompatApi),
        }
    )
}

export const getOrganizationsProjectsGenerateConversationsPublicTokenCreateUrl = (
    organizationId: string,
    id: number
) => {
    return `/api/organizations/${organizationId}/projects/${id}/generate_conversations_public_token/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsGenerateConversationsPublicTokenCreate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi?: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsGenerateConversationsPublicTokenCreateUrl(organizationId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(projectBackwardCompatApi),
        }
    )
}

export const getOrganizationsProjectsIsGeneratingDemoDataRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/is_generating_demo_data/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsIsGeneratingDemoDataRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsIsGeneratingDemoDataRetrieveUrl(organizationId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getOrganizationsProjectsLogsConfigRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/logs_config/`
}

/**
 * Manage logs product configuration for this project's canonical environment.
 * Mirrors the env-router action so /api/projects/:id/logs_config/ resolves
 * alongside the legacy /api/environments/:id/logs_config/ alias.
 */
export const organizationsProjectsLogsConfigRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getOrganizationsProjectsLogsConfigRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getOrganizationsProjectsLogsConfigPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/logs_config/`
}

/**
 * Manage logs product configuration for this project's canonical environment.
 * Mirrors the env-router action so /api/projects/:id/logs_config/ resolves
 * alongside the legacy /api/environments/:id/logs_config/ alias.
 */
export const organizationsProjectsLogsConfigPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi?: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsLogsConfigPartialUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedProjectBackwardCompatApi),
        }
    )
}

export const getOrganizationsProjectsResetTokenPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/reset_token/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsResetTokenPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi?: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsResetTokenPartialUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedProjectBackwardCompatApi),
        }
    )
}

export const getOrganizationsProjectsRotateSecretTokenPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/rotate_secret_token/`
}

/**
 * Projects for the current organization.
 */
export const organizationsProjectsRotateSecretTokenPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi?: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(
        getOrganizationsProjectsRotateSecretTokenPartialUpdateUrl(organizationId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedProjectBackwardCompatApi),
        }
    )
}

export const getOrganizationsProjectsSettingsAsOfRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/settings_as_of/`
}

/**
 * Return the project settings as of the provided timestamp.
 * Query params:
 * - at: ISO8601 datetime (required)
 * - scope: optional, one or multiple keys to filter the returned settings
 */
export const organizationsProjectsSettingsAsOfRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getOrganizationsProjectsSettingsAsOfRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDashboardsSharingListUrl = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/`
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

export const getDashboardsSharingPasswordsCreateUrl = (projectId: string, dashboardId: number) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/passwords/`
}

/**
 * Create a new password for the sharing configuration.
 */
export const dashboardsSharingPasswordsCreate = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi?: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getDashboardsSharingPasswordsCreateUrl(projectId, dashboardId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

export const getDashboardsSharingPasswordsDestroyUrl = (projectId: string, dashboardId: number, passwordId: string) => {
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/passwords/${passwordId}/`
}

/**
 * Delete a password from the sharing configuration.
 */
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
    return `/api/projects/${projectId}/dashboards/${dashboardId}/sharing/refresh/`
}

export const dashboardsSharingRefreshCreate = async (
    projectId: string,
    dashboardId: number,
    sharingConfigurationApi?: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getDashboardsSharingRefreshCreateUrl(projectId, dashboardId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

export const getDesktopFileSystemListUrl = (projectId: string, params?: DesktopFileSystemListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/desktop_file_system/?${stringifiedParams}`
        : `/api/projects/${projectId}/desktop_file_system/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemList = async (
    projectId: string,
    params?: DesktopFileSystemListParams,
    options?: RequestInit
): Promise<PaginatedFileSystemListApi> => {
    return apiMutator<PaginatedFileSystemListApi>(getDesktopFileSystemListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDesktopFileSystemCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/desktop_file_system/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<FileSystemApi> => {
    return apiMutator<FileSystemApi>(getDesktopFileSystemCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getDesktopFileSystemRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<FileSystemApi> => {
    return apiMutator<FileSystemApi>(getDesktopFileSystemRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDesktopFileSystemUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemUpdate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<FileSystemApi> => {
    return apiMutator<FileSystemApi>(getDesktopFileSystemUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getDesktopFileSystemPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemPartialUpdate = async (
    projectId: string,
    id: string,
    patchedFileSystemApi?: NonReadonly<PatchedFileSystemApi>,
    options?: RequestInit
): Promise<FileSystemApi> => {
    return apiMutator<FileSystemApi>(getDesktopFileSystemPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFileSystemApi),
    })
}

export const getDesktopFileSystemDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDesktopFileSystemDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDesktopFileSystemCanvasPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/canvas/`
}

/**
 * Publish a new version of a freeform canvas's React source.
 *
 * Merges into the dashboard row's `meta` (never replaces it), so existing
 * keys like `channelId`/`templateId` survive. Appends a full-file version
 * snapshot and points `currentVersionId` at it — the server-side mirror of
 * the app's dashboardsService.saveFreeform.
 */
export const desktopFileSystemCanvasPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCanvasPublishApi?: PatchedCanvasPublishApi,
    options?: RequestInit
): Promise<FileSystemApi> => {
    return apiMutator<FileSystemApi>(getDesktopFileSystemCanvasPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCanvasPublishApi),
    })
}

export const getDesktopFileSystemContextGenerationRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/context_generation/`
}

/**
 * Return the Task currently generating this folder's CONTEXT.md, or null if none.
 */
export const desktopFileSystemContextGenerationRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ContextGenerationApi> => {
    return apiMutator<ContextGenerationApi>(getDesktopFileSystemContextGenerationRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDesktopFileSystemContextGenerationUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/context_generation/`
}

/**
 * Set or clear the Task associated with this folder's CONTEXT.md generation.
 */
export const desktopFileSystemContextGenerationUpdate = async (
    projectId: string,
    id: string,
    contextGenerationSetApi: ContextGenerationSetApi,
    options?: RequestInit
): Promise<ContextGenerationApi> => {
    return apiMutator<ContextGenerationApi>(getDesktopFileSystemContextGenerationUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(contextGenerationSetApi),
    })
}

export const getDesktopFileSystemCountCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/count/`
}

/**
 * Get count of all files in a folder.
 */
export const desktopFileSystemCountCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDesktopFileSystemCountCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getDesktopFileSystemInstructionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/instructions/`
}

/**
 * Return the latest non-deleted instructions for this folder.
 */
export const desktopFileSystemInstructionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<FolderInstructionsApi> => {
    return apiMutator<FolderInstructionsApi>(getDesktopFileSystemInstructionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDesktopFileSystemInstructionsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/instructions/`
}

/**
 * Publish a new version of the folder's instructions.
 */
export const desktopFileSystemInstructionsUpdate = async (
    projectId: string,
    id: string,
    folderInstructionsPublishApi: FolderInstructionsPublishApi,
    options?: RequestInit
): Promise<FolderInstructionsApi> => {
    return apiMutator<FolderInstructionsApi>(getDesktopFileSystemInstructionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(folderInstructionsPublishApi),
    })
}

export const getDesktopFileSystemInstructionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/instructions/`
}

/**
 * Publish a new version of the folder's instructions.
 */
export const desktopFileSystemInstructionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedFolderInstructionsPublishApi?: PatchedFolderInstructionsPublishApi,
    options?: RequestInit
): Promise<FolderInstructionsApi> => {
    return apiMutator<FolderInstructionsApi>(getDesktopFileSystemInstructionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFolderInstructionsPublishApi),
    })
}

export const getDesktopFileSystemInstructionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/instructions/`
}

/**
 * Soft-delete every version of this folder's instructions.
 */
export const desktopFileSystemInstructionsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDesktopFileSystemInstructionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDesktopFileSystemInstructionsVersionsListUrl = (
    projectId: string,
    id: string,
    params?: DesktopFileSystemInstructionsVersionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/desktop_file_system/${id}/instructions/versions/?${stringifiedParams}`
        : `/api/projects/${projectId}/desktop_file_system/${id}/instructions/versions/`
}

/**
 * List the version history for this folder's instructions, newest first.
 */
export const desktopFileSystemInstructionsVersionsList = async (
    projectId: string,
    id: string,
    params?: DesktopFileSystemInstructionsVersionsListParams,
    options?: RequestInit
): Promise<PaginatedFolderInstructionsVersionListApi> => {
    return apiMutator<PaginatedFolderInstructionsVersionListApi>(
        getDesktopFileSystemInstructionsVersionsListUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getDesktopFileSystemLinkCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/link/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemLinkCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDesktopFileSystemLinkCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getDesktopFileSystemMoveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system/${id}/move/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemMoveCreate = async (
    projectId: string,
    id: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDesktopFileSystemMoveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getDesktopFileSystemCountByPathCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/desktop_file_system/count_by_path/`
}

/**
 * Get count of all files in a folder.
 */
export const desktopFileSystemCountByPathCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDesktopFileSystemCountByPathCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getDesktopFileSystemLogViewRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/desktop_file_system/log_view/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemLogViewRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDesktopFileSystemLogViewRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDesktopFileSystemLogViewCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/desktop_file_system/log_view/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemLogViewCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDesktopFileSystemLogViewCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getDesktopFileSystemUndoDeleteCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/desktop_file_system/undo_delete/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemUndoDeleteCreate = async (
    projectId: string,
    fileSystemApi: NonReadonly<FileSystemApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDesktopFileSystemUndoDeleteCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemApi),
    })
}

export const getDesktopFileSystemUnfiledRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/desktop_file_system/unfiled/`
}

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemUnfiledRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getDesktopFileSystemUnfiledRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getDesktopFileSystemShortcutListUrl = (
    projectId: string,
    params?: DesktopFileSystemShortcutListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/desktop_file_system_shortcut/?${stringifiedParams}`
        : `/api/projects/${projectId}/desktop_file_system_shortcut/`
}

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutList = async (
    projectId: string,
    params?: DesktopFileSystemShortcutListParams,
    options?: RequestInit
): Promise<PaginatedFileSystemShortcutListApi> => {
    return apiMutator<PaginatedFileSystemShortcutListApi>(getDesktopFileSystemShortcutListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDesktopFileSystemShortcutCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/desktop_file_system_shortcut/`
}

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutCreate = async (
    projectId: string,
    fileSystemShortcutApi: NonReadonly<FileSystemShortcutApi>,
    options?: RequestInit
): Promise<FileSystemShortcutApi> => {
    return apiMutator<FileSystemShortcutApi>(getDesktopFileSystemShortcutCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemShortcutApi),
    })
}

export const getDesktopFileSystemShortcutRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system_shortcut/${id}/`
}

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<FileSystemShortcutApi> => {
    return apiMutator<FileSystemShortcutApi>(getDesktopFileSystemShortcutRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDesktopFileSystemShortcutUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system_shortcut/${id}/`
}

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutUpdate = async (
    projectId: string,
    id: string,
    fileSystemShortcutApi: NonReadonly<FileSystemShortcutApi>,
    options?: RequestInit
): Promise<FileSystemShortcutApi> => {
    return apiMutator<FileSystemShortcutApi>(getDesktopFileSystemShortcutUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemShortcutApi),
    })
}

export const getDesktopFileSystemShortcutPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system_shortcut/${id}/`
}

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutPartialUpdate = async (
    projectId: string,
    id: string,
    patchedFileSystemShortcutApi?: NonReadonly<PatchedFileSystemShortcutApi>,
    options?: RequestInit
): Promise<FileSystemShortcutApi> => {
    return apiMutator<FileSystemShortcutApi>(getDesktopFileSystemShortcutPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFileSystemShortcutApi),
    })
}

export const getDesktopFileSystemShortcutDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/desktop_file_system_shortcut/${id}/`
}

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDesktopFileSystemShortcutDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getDesktopFileSystemShortcutReorderCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/desktop_file_system_shortcut/reorder/`
}

/**
 * Set the display order of the current user's shortcuts. `ordered_ids` becomes the new top-to-bottom order; any unknown IDs are rejected.
 */
export const desktopFileSystemShortcutReorderCreate = async (
    projectId: string,
    fileSystemShortcutReorderApi: FileSystemShortcutReorderApi,
    options?: RequestInit
): Promise<PaginatedFileSystemShortcutListApi> => {
    return apiMutator<PaginatedFileSystemShortcutListApi>(getDesktopFileSystemShortcutReorderCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemShortcutReorderApi),
    })
}

export const getExportsListUrl = (projectId: string, params?: ExportsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
    patchedFileSystemApi?: NonReadonly<PatchedFileSystemApi>,
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

export const getFileSystemCountCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system/${id}/count/`
}

/**
 * Get count of all files in a folder.
 */
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

export const getFileSystemCountByPathCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system/count_by_path/`
}

/**
 * Get count of all files in a folder.
 */
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

export const getFileSystemShortcutListUrl = (projectId: string, params?: FileSystemShortcutListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/file_system_shortcut/?${stringifiedParams}`
        : `/api/projects/${projectId}/file_system_shortcut/`
}

export const fileSystemShortcutList = async (
    projectId: string,
    params?: FileSystemShortcutListParams,
    options?: RequestInit
): Promise<PaginatedFileSystemShortcutListApi> => {
    return apiMutator<PaginatedFileSystemShortcutListApi>(getFileSystemShortcutListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getFileSystemShortcutCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system_shortcut/`
}

export const fileSystemShortcutCreate = async (
    projectId: string,
    fileSystemShortcutApi: NonReadonly<FileSystemShortcutApi>,
    options?: RequestInit
): Promise<FileSystemShortcutApi> => {
    return apiMutator<FileSystemShortcutApi>(getFileSystemShortcutCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemShortcutApi),
    })
}

export const getFileSystemShortcutRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system_shortcut/${id}/`
}

export const fileSystemShortcutRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<FileSystemShortcutApi> => {
    return apiMutator<FileSystemShortcutApi>(getFileSystemShortcutRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getFileSystemShortcutUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system_shortcut/${id}/`
}

export const fileSystemShortcutUpdate = async (
    projectId: string,
    id: string,
    fileSystemShortcutApi: NonReadonly<FileSystemShortcutApi>,
    options?: RequestInit
): Promise<FileSystemShortcutApi> => {
    return apiMutator<FileSystemShortcutApi>(getFileSystemShortcutUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemShortcutApi),
    })
}

export const getFileSystemShortcutPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system_shortcut/${id}/`
}

export const fileSystemShortcutPartialUpdate = async (
    projectId: string,
    id: string,
    patchedFileSystemShortcutApi?: NonReadonly<PatchedFileSystemShortcutApi>,
    options?: RequestInit
): Promise<FileSystemShortcutApi> => {
    return apiMutator<FileSystemShortcutApi>(getFileSystemShortcutPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFileSystemShortcutApi),
    })
}

export const getFileSystemShortcutDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/file_system_shortcut/${id}/`
}

export const fileSystemShortcutDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getFileSystemShortcutDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getFileSystemShortcutReorderCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/file_system_shortcut/reorder/`
}

/**
 * Set the display order of the current user's shortcuts. `ordered_ids` becomes the new top-to-bottom order; any unknown IDs are rejected.
 */
export const fileSystemShortcutReorderCreate = async (
    projectId: string,
    fileSystemShortcutReorderApi: FileSystemShortcutReorderApi,
    options?: RequestInit
): Promise<PaginatedFileSystemShortcutListApi> => {
    return apiMutator<PaginatedFileSystemShortcutListApi>(getFileSystemShortcutReorderCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(fileSystemShortcutReorderApi),
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

export const getInsightsSharingPasswordsCreateUrl = (projectId: string, insightId: number) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/passwords/`
}

/**
 * Create a new password for the sharing configuration.
 */
export const insightsSharingPasswordsCreate = async (
    projectId: string,
    insightId: number,
    sharingConfigurationApi?: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getInsightsSharingPasswordsCreateUrl(projectId, insightId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

export const getInsightsSharingPasswordsDestroyUrl = (projectId: string, insightId: number, passwordId: string) => {
    return `/api/projects/${projectId}/insights/${insightId}/sharing/passwords/${passwordId}/`
}

/**
 * Delete a password from the sharing configuration.
 */
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
    sharingConfigurationApi?: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getInsightsSharingRefreshCreateUrl(projectId, insightId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

export const getNotebooksSharingListUrl = (projectId: string, notebookId: string) => {
    return `/api/projects/${projectId}/notebooks/${notebookId}/sharing/`
}

export const notebooksSharingList = async (
    projectId: string,
    notebookId: string,
    options?: RequestInit
): Promise<SharingConfigurationApi[]> => {
    return apiMutator<SharingConfigurationApi[]>(getNotebooksSharingListUrl(projectId, notebookId), {
        ...options,
        method: 'GET',
    })
}

export const getNotebooksSharingPasswordsCreateUrl = (projectId: string, notebookId: string) => {
    return `/api/projects/${projectId}/notebooks/${notebookId}/sharing/passwords/`
}

/**
 * Create a new password for the sharing configuration.
 */
export const notebooksSharingPasswordsCreate = async (
    projectId: string,
    notebookId: string,
    sharingConfigurationApi?: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getNotebooksSharingPasswordsCreateUrl(projectId, notebookId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

export const getNotebooksSharingPasswordsDestroyUrl = (projectId: string, notebookId: string, passwordId: string) => {
    return `/api/projects/${projectId}/notebooks/${notebookId}/sharing/passwords/${passwordId}/`
}

/**
 * Delete a password from the sharing configuration.
 */
export const notebooksSharingPasswordsDestroy = async (
    projectId: string,
    notebookId: string,
    passwordId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getNotebooksSharingPasswordsDestroyUrl(projectId, notebookId, passwordId), {
        ...options,
        method: 'DELETE',
    })
}

export const getNotebooksSharingRefreshCreateUrl = (projectId: string, notebookId: string) => {
    return `/api/projects/${projectId}/notebooks/${notebookId}/sharing/refresh/`
}

export const notebooksSharingRefreshCreate = async (
    projectId: string,
    notebookId: string,
    sharingConfigurationApi?: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getNotebooksSharingRefreshCreateUrl(projectId, notebookId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

export const getProductEnablementCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/product_enablement/`
}

export const productEnablementCreate = async (
    projectId: string,
    productEnablementApi: ProductEnablementApi,
    options?: RequestInit
): Promise<ProductEnablementResultApi> => {
    return apiMutator<ProductEnablementResultApi>(getProductEnablementCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(productEnablementApi),
    })
}

export const getProjectSecretApiKeysListUrl = (projectId: string, params?: ProjectSecretApiKeysListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/project_secret_api_keys/?${stringifiedParams}`
        : `/api/projects/${projectId}/project_secret_api_keys/`
}

export const projectSecretApiKeysList = async (
    projectId: string,
    params?: ProjectSecretApiKeysListParams,
    options?: RequestInit
): Promise<PaginatedProjectSecretAPIKeyListApi> => {
    return apiMutator<PaginatedProjectSecretAPIKeyListApi>(getProjectSecretApiKeysListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getProjectSecretApiKeysCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/project_secret_api_keys/`
}

export const projectSecretApiKeysCreate = async (
    projectId: string,
    projectSecretAPIKeyApi: NonReadonly<ProjectSecretAPIKeyApi>,
    options?: RequestInit
): Promise<ProjectSecretAPIKeyApi> => {
    return apiMutator<ProjectSecretAPIKeyApi>(getProjectSecretApiKeysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectSecretAPIKeyApi),
    })
}

export const getProjectSecretApiKeysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/project_secret_api_keys/${id}/`
}

export const projectSecretApiKeysRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ProjectSecretAPIKeyApi> => {
    return apiMutator<ProjectSecretAPIKeyApi>(getProjectSecretApiKeysRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getProjectSecretApiKeysUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/project_secret_api_keys/${id}/`
}

export const projectSecretApiKeysUpdate = async (
    projectId: string,
    id: string,
    projectSecretAPIKeyApi: NonReadonly<ProjectSecretAPIKeyApi>,
    options?: RequestInit
): Promise<ProjectSecretAPIKeyApi> => {
    return apiMutator<ProjectSecretAPIKeyApi>(getProjectSecretApiKeysUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectSecretAPIKeyApi),
    })
}

export const getProjectSecretApiKeysPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/project_secret_api_keys/${id}/`
}

export const projectSecretApiKeysPartialUpdate = async (
    projectId: string,
    id: string,
    patchedProjectSecretAPIKeyApi?: NonReadonly<PatchedProjectSecretAPIKeyApi>,
    options?: RequestInit
): Promise<ProjectSecretAPIKeyApi> => {
    return apiMutator<ProjectSecretAPIKeyApi>(getProjectSecretApiKeysPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectSecretAPIKeyApi),
    })
}

export const getProjectSecretApiKeysDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/project_secret_api_keys/${id}/`
}

export const projectSecretApiKeysDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getProjectSecretApiKeysDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getProjectSecretApiKeysRollCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/project_secret_api_keys/${id}/roll/`
}

/**
 * Roll a project secret API key
 */
export const projectSecretApiKeysRollCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ProjectSecretAPIKeyApi> => {
    return apiMutator<ProjectSecretAPIKeyApi>(getProjectSecretApiKeysRollCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getPropertyDefinitionsListUrl = (projectId: string, params?: PropertyDefinitionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
    enterprisePropertyDefinitionApi?: NonReadonly<EnterprisePropertyDefinitionApi>,
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
    patchedEnterprisePropertyDefinitionApi?: NonReadonly<PatchedEnterprisePropertyDefinitionApi>,
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

export const getPropertyDefinitionsBulkUpdateTagsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/property_definitions/bulk_update_tags/`
}

/**
 * Bulk update tags on multiple objects.
 *
 * PAT access: this action has no ``required_scopes=`` on the decorator —
 * inheriting viewsets must add ``"bulk_update_tags"`` to their
 * ``scope_object_write_actions`` list to accept personal API keys.
 * Without that opt-in, ``APIScopePermission`` rejects PAT requests with
 * "This action does not support personal API key access". Done per-viewset
 * so granting ``<scope>:write`` for one resource doesn't leak access to
 * sibling resources that share this mixin.
 *
 * Accepts:
 * - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}
 *
 * Actions:
 * - "add": Add tags to existing tags on each object
 * - "remove": Remove specific tags from each object
 * - "set": Replace all tags on each object with the provided list
 */
export const propertyDefinitionsBulkUpdateTagsCreate = async (
    projectId: string,
    bulkUpdateTagsRequestApi: BulkUpdateTagsRequestApi,
    options?: RequestInit
): Promise<BulkUpdateTagsResponseApi> => {
    return apiMutator<BulkUpdateTagsResponseApi>(getPropertyDefinitionsBulkUpdateTagsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bulkUpdateTagsRequestApi),
    })
}

export const getPropertyDefinitionsSeenTogetherRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/property_definitions/seen_together/`
}

/**
 * Allows a caller to provide a list of event names and a single property name
 * Returns a map of the event names to a boolean representing whether that property has ever been seen with that event_name
 */
export const propertyDefinitionsSeenTogetherRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getPropertyDefinitionsSeenTogetherRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
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

export const getSessionRecordingsSharingPasswordsCreateUrl = (projectId: string, recordingId: string) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/passwords/`
}

/**
 * Create a new password for the sharing configuration.
 */
export const sessionRecordingsSharingPasswordsCreate = async (
    projectId: string,
    recordingId: string,
    sharingConfigurationApi?: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getSessionRecordingsSharingPasswordsCreateUrl(projectId, recordingId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

export const getSessionRecordingsSharingPasswordsDestroyUrl = (
    projectId: string,
    recordingId: string,
    passwordId: string
) => {
    return `/api/projects/${projectId}/session_recordings/${recordingId}/sharing/passwords/${passwordId}/`
}

/**
 * Delete a password from the sharing configuration.
 */
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
    sharingConfigurationApi?: NonReadonly<SharingConfigurationApi>,
    options?: RequestInit
): Promise<SharingConfigurationApi> => {
    return apiMutator<SharingConfigurationApi>(getSessionRecordingsSharingRefreshCreateUrl(projectId, recordingId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sharingConfigurationApi),
    })
}

export const getUsersListUrl = (params?: UsersListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
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

/**
 * Retrieve a user's profile and settings. Pass `@me` as the UUID to fetch the authenticated user; non-staff callers may only access their own account.
 */
export const usersRetrieve = async (uuid: string, options?: RequestInit): Promise<UserApi> => {
    return apiMutator<UserApi>(getUsersRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

export const getUsersUpdateUrl = (uuid: string) => {
    return `/api/users/${uuid}/`
}

/**
 * Replace the authenticated user's profile and settings. Pass `@me` as the UUID to update the authenticated user. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
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

/**
 * Update one or more of the authenticated user's profile fields or settings.
 */
export const usersPartialUpdate = async (
    uuid: string,
    patchedUserApi?: NonReadonly<PatchedUserApi>,
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

export const getUsersCredentialsReviewCompleteCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/credentials_review_complete/`
}

/**
 * Mark the user as having reviewed their existing credentials. Idempotent. Flips `requires_credential_review` to False so the post-login interstitial isn't shown again. Does not modify any credentials; the user revokes individual Personal API Keys and passkeys via their existing endpoints from the same screen.
 */
export const usersCredentialsReviewCompleteCreate = async (uuid: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUsersCredentialsReviewCompleteCreateUrl(uuid), {
        ...options,
        method: 'POST',
    })
}

export const getUsersGithubLoginRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/github_login/`
}

export const usersGithubLoginRetrieve = async (uuid: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUsersGithubLoginRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
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
    patchedUserApi?: NonReadonly<PatchedUserApi>,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersHedgehogConfigPartialUpdateUrl(uuid), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUserApi),
    })
}

export const getUsersIntegrationsListUrl = (uuid: string, params?: UsersIntegrationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/users/${uuid}/integrations/?${stringifiedParams}`
        : `/api/users/${uuid}/integrations/`
}

/**
 * Return the authenticated user's personal integrations of a given
 * ``kind`` (``github`` or ``slack``).
 *
 * The response shape varies per kind because the underlying ``UserIntegration``
 * rows carry different identity fields — GitHub rows expose
 * ``installation_id`` / ``account`` / ``uses_shared_installation``; Slack
 * rows expose ``slack_user_id`` / ``slack_team_id`` / ``slack_team_name``.
 * Kind-specific destroy and start actions remain split so their distinct
 * semantics (e.g. Slack's lack of "uninstall on last reference") stay
 * explicit at the URL layer.
 *
 * Default of ``kind=github`` is load-bearing: mobile (``apps/mobile/...``)
 * and the Code SDK (``packages/api-client/...``) both call this endpoint
 * without a query param today and rely on receiving GitHub rows.
 * @summary List the user's personal integrations of a given kind
 */
export const usersIntegrationsList = async (
    uuid: string,
    params?: UsersIntegrationsListParams,
    options?: RequestInit
): Promise<PaginatedUserGitHubIntegrationListResponseListApi> => {
    return apiMutator<PaginatedUserGitHubIntegrationListResponseListApi>(getUsersIntegrationsListUrl(uuid, params), {
        ...options,
        method: 'GET',
    })
}

export const getUsersIntegrationsGithubDestroyUrl = (uuid: string, installationId: string) => {
    return `/api/users/${uuid}/integrations/github/${installationId}/`
}

/**
 * Remove a specific GitHub installation by its installation_id.
 * @summary Disconnect a personal GitHub integration
 */
export const usersIntegrationsGithubDestroy = async (
    uuid: string,
    installationId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersIntegrationsGithubDestroyUrl(uuid, installationId), {
        ...options,
        method: 'DELETE',
    })
}

export const getUsersIntegrationsGithubBranchesRetrieveUrl = (
    uuid: string,
    installationId: string,
    params: UsersIntegrationsGithubBranchesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/users/${uuid}/integrations/github/${installationId}/branches/?${stringifiedParams}`
        : `/api/users/${uuid}/integrations/github/${installationId}/branches/`
}

/**
 * List branches for a repository accessible to a personal GitHub installation.
 * @summary List branches for a personal GitHub installation repository
 */
export const usersIntegrationsGithubBranchesRetrieve = async (
    uuid: string,
    installationId: string,
    params: UsersIntegrationsGithubBranchesRetrieveParams,
    options?: RequestInit
): Promise<GitHubBranchesResponseApi> => {
    return apiMutator<GitHubBranchesResponseApi>(
        getUsersIntegrationsGithubBranchesRetrieveUrl(uuid, installationId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getUsersIntegrationsGithubReposRetrieveUrl = (
    uuid: string,
    installationId: string,
    params?: UsersIntegrationsGithubReposRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/users/${uuid}/integrations/github/${installationId}/repos/?${stringifiedParams}`
        : `/api/users/${uuid}/integrations/github/${installationId}/repos/`
}

/**
 * List repositories accessible to a specific GitHub installation (paginated, cached).
 * @summary List repositories for a personal GitHub installation
 */
export const usersIntegrationsGithubReposRetrieve = async (
    uuid: string,
    installationId: string,
    params?: UsersIntegrationsGithubReposRetrieveParams,
    options?: RequestInit
): Promise<GitHubReposResponseApi> => {
    return apiMutator<GitHubReposResponseApi>(
        getUsersIntegrationsGithubReposRetrieveUrl(uuid, installationId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getUsersIntegrationsGithubReposRefreshCreateUrl = (uuid: string, installationId: string) => {
    return `/api/users/${uuid}/integrations/github/${installationId}/repos/refresh/`
}

/**
 * Refresh repositories accessible to a specific GitHub installation.
 * @summary Refresh repositories for a personal GitHub installation
 */
export const usersIntegrationsGithubReposRefreshCreate = async (
    uuid: string,
    installationId: string,
    options?: RequestInit
): Promise<GitHubReposRefreshResponseApi> => {
    return apiMutator<GitHubReposRefreshResponseApi>(
        getUsersIntegrationsGithubReposRefreshCreateUrl(uuid, installationId),
        {
            ...options,
            method: 'POST',
        }
    )
}

export const getUsersIntegrationsGithubPrepareCallbackCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/integrations/github/prepare_callback/`
}

/**
 * Seed personal GitHub manage callback state before opening installation settings on GitHub.
 */
export const usersIntegrationsGithubPrepareCallbackCreate = async (
    uuid: string,
    userGitHubPrepareCallbackRequestApi: UserGitHubPrepareCallbackRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersIntegrationsGithubPrepareCallbackCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userGitHubPrepareCallbackRequestApi),
    })
}

export const getUsersIntegrationsGithubStartCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/integrations/github/start/`
}

/**
 * Start GitHub linking: either full App install or OAuth-only (user-to-server).
 *
 * ``**_kwargs`` absorbs ``parent_lookup_uuid`` from the nested
 * ``/api/users/{uuid}/integrations/`` router (same pattern as ``local_evaluation``
 * under projects).
 *
 * Usually returns ``install_url`` pointing at ``/installations/new`` so the
 * user can pick any GitHub org (new or already connected).  GitHub's install
 * page handles both cases: orgs where the app is installed show "Configure"
 * (no admin needed), orgs where it isn't show "Install" (needs admin).
 *
 * **OAuth fast path:** when the current project already has a team-level
 * GitHub installation, and the user has no ``UserIntegration`` for that
 * installation yet, we skip the org picker and redirect straight to
 * ``/login/oauth/authorize`` so the user only authorizes themselves.
 * ``connect_from`` is preserved for first-party clients so they return to
 * the originating client immediately.
 *
 * In both cases the response key is ``install_url`` for compatibility with callers.
 * @summary Start GitHub personal integration linking
 */
export const usersIntegrationsGithubStartCreate = async (
    uuid: string,
    userGitHubLinkStartRequestApi?: UserGitHubLinkStartRequestApi,
    options?: RequestInit
): Promise<UserGitHubLinkStartResponseApi> => {
    return apiMutator<UserGitHubLinkStartResponseApi>(getUsersIntegrationsGithubStartCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userGitHubLinkStartRequestApi),
    })
}

export const getUsersIntegrationsSlackDestroyUrl = (uuid: string, slackUserId: string) => {
    return `/api/users/${uuid}/integrations/slack/${slackUserId}/`
}

/**
 * Remove a Slack identity link by Slack user id. Idempotent and
 * flag-agnostic — users must always be able to unlink even after the
 * feature flag is turned off.
 * @summary Unlink a Slack identity
 */
export const usersIntegrationsSlackDestroy = async (
    uuid: string,
    slackUserId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersIntegrationsSlackDestroyUrl(uuid, slackUserId), {
        ...options,
        method: 'DELETE',
    })
}

export const getUsersIntegrationsSlackLinkableWorkspacesRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/integrations/slack/linkable_workspaces/`
}

/**
 * Return Slack workspaces in the user's organizations that they have
 * not yet linked. The settings UI uses this list to decide whether to
 * show a "Link my Slack account" button (non-empty list) and what to
 * offer in the picker when several are connectable.
 * @summary List Slack workspaces this user could link to
 */
export const usersIntegrationsSlackLinkableWorkspacesRetrieve = async (
    uuid: string,
    options?: RequestInit
): Promise<UserSlackLinkableWorkspaceListResponseApi> => {
    return apiMutator<UserSlackLinkableWorkspaceListResponseApi>(
        getUsersIntegrationsSlackLinkableWorkspacesRetrieveUrl(uuid),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getUsersIntegrationsSlackStartCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/integrations/slack/start/`
}

/**
 * Mint a Sign-in-with-Slack invite URL initiated from settings, without
 * Slack-DM context. The returned URL takes the user through PostHog login
 * (already satisfied here), then to Slack OAuth, then back to our callback
 * which writes the ``UserIntegration`` row.
 *
 * Without body params, falls back to the user's ``current_team`` and that
 * team's first Slack ``Integration`` — works when there's exactly one
 * linkable workspace. With ``team_id`` + ``slack_team_id``, links against
 * the exact pair (what the frontend uses when a picker is shown).
 *
 * Refuses if the target team has no matching Slack workspace, if the
 * feature flag is off for the workspace, or if the user is already linked
 * to it.
 * @summary Start Slack identity link from settings
 */
export const usersIntegrationsSlackStartCreate = async (
    uuid: string,
    userSlackLinkStartRequestApi?: UserSlackLinkStartRequestApi,
    options?: RequestInit
): Promise<UserSlackLinkStartResponseApi> => {
    return apiMutator<UserSlackLinkStartResponseApi>(getUsersIntegrationsSlackStartCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userSlackLinkStartRequestApi),
    })
}

export const getUsersLoginSessionsListUrl = (uuid: string, params?: UsersLoginSessionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/users/${uuid}/login_sessions/?${stringifiedParams}`
        : `/api/users/${uuid}/login_sessions/`
}

/**
 * List the cookie-auth login sessions for the current user. Self-only — never another user.
 */
export const usersLoginSessionsList = async (
    uuid: string,
    params?: UsersLoginSessionsListParams,
    options?: RequestInit
): Promise<UserAuthSessionApi[]> => {
    return apiMutator<UserAuthSessionApi[]>(getUsersLoginSessionsListUrl(uuid, params), {
        ...options,
        method: 'GET',
    })
}

export const getUsersLoginSessionsDestroyUrl = (uuid: string, sessionId: string) => {
    return `/api/users/${uuid}/login_sessions/${sessionId}/`
}

/**
 * Revoke a single login session belonging to the current user. Self-only.
 *
 * Requires recent auth (TimeSensitiveActionPermission) so a stolen cookie can't weaponize
 * revocation, and is blocked while impersonating via ImpersonationBlockedPathsMiddleware.
 */
export const usersLoginSessionsDestroy = async (
    uuid: string,
    sessionId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersLoginSessionsDestroyUrl(uuid, sessionId), {
        ...options,
        method: 'DELETE',
    })
}

export const getUsersLoginSessionsRevokeOthersCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/login_sessions/revoke_others/`
}

/**
 * Revoke every login session for the current user except the one making this request. Self-only.
 *
 * Requires recent auth (TimeSensitiveActionPermission) so a stolen cookie can't weaponize the
 * "log out everywhere else" lock-out, and is blocked while impersonating.
 */
export const usersLoginSessionsRevokeOthersCreate = async (
    uuid: string,
    options?: RequestInit
): Promise<RevokeOtherSessionsResponseApi> => {
    return apiMutator<RevokeOtherSessionsResponseApi>(getUsersLoginSessionsRevokeOthersCreateUrl(uuid), {
        ...options,
        method: 'POST',
    })
}

export const getUsersOnboardingSkipCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/onboarding/skip/`
}

/**
 * Mark the current user as having exited onboarding with a non-delegated reason.
 * Idempotent: the skip timestamp is only set on the first successful call.
 *
 * Callers wanting to delegate setup to a teammate must use the dedicated
 * /organizations/{id}/invites/delegate/ endpoint, which atomically creates the
 * invite and sets reason="delegated". This endpoint rejects that reason so state
 * can't be faked without a real invite.
 */
export const usersOnboardingSkipCreate = async (
    uuid: string,
    onboardingSkipRequestApi: OnboardingSkipRequestApi,
    options?: RequestInit
): Promise<UserApi> => {
    return apiMutator<UserApi>(getUsersOnboardingSkipCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(onboardingSkipRequestApi),
    })
}

export const getUsersPushTokensCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/push_tokens/`
}

/**
 * Idempotent upsert: if the (user, token) pair already exists, `platform` and `last_seen_at` are refreshed. Otherwise a new row is created.
 * @summary Register a push notification token
 */
export const usersPushTokensCreate = async (
    uuid: string,
    userPushTokenRegisterRequestApi: UserPushTokenRegisterRequestApi,
    options?: RequestInit
): Promise<UserPushTokenItemApi> => {
    return apiMutator<UserPushTokenItemApi>(getUsersPushTokensCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userPushTokenRegisterRequestApi),
    })
}

export const getUsersPushTokensUnregisterCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/push_tokens/unregister/`
}

/**
 * Delete the row matching `(user, token)`. Returns 204 even if no row matches so the mobile client can call this unconditionally when the user opts out.
 * @summary Unregister a push notification token
 */
export const usersPushTokensUnregisterCreate = async (
    uuid: string,
    userPushTokenUnregisterRequestApi: UserPushTokenUnregisterRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUsersPushTokensUnregisterCreateUrl(uuid), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(userPushTokenUnregisterRequestApi),
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

export const getUsersTwoFactorBackupCodesCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_backup_codes/`
}

/**
 * Generate new backup codes, invalidating any existing ones
 */
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

export const getUsersTwoFactorDisableCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_disable/`
}

/**
 * Disable 2FA and remove all related devices
 */
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

export const getUsersTwoFactorStatusRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/two_factor_status/`
}

/**
 * Get current 2FA status including backup codes if enabled
 */
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
    patchedUserApi?: NonReadonly<PatchedUserApi>,
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
