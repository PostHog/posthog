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
    DashboardTemplateApi,
    DomainsListParams,
    EnterprisePropertyDefinitionApi,
    ExportedAssetApi,
    ExportsListParams,
    FileSystemApi,
    FileSystemListParams,
    FlagValueResponseApi,
    FlagValueValuesRetrieveParams,
    InvitesListParams,
    OauthApplicationsListParams,
    OnboardingSkipRequestApi,
    OrganizationDomainApi,
    OrganizationInviteApi,
    OrganizationInviteDelegateApi,
    OrganizationsProjectsListParams,
    PaginatedEnterprisePropertyDefinitionListApi,
    PaginatedExportedAssetListApi,
    PaginatedFileSystemListApi,
    PaginatedOrganizationDomainListApi,
    PaginatedOrganizationInviteListApi,
    PaginatedOrganizationOAuthApplicationListApi,
    PaginatedProjectBackwardCompatBasicListApi,
    PaginatedProjectSecretAPIKeyListApi,
    PaginatedSubscriptionDeliveryListApi,
    PaginatedSubscriptionListApi,
    PaginatedUserListApi,
    PatchedDashboardTemplateApi,
    PatchedEnterprisePropertyDefinitionApi,
    PatchedFileSystemApi,
    PatchedOrganizationDomainApi,
    PatchedProjectBackwardCompatApi,
    PatchedProjectSecretAPIKeyApi,
    PatchedSubscriptionApi,
    PatchedUserApi,
    ProjectBackwardCompatApi,
    ProjectSecretAPIKeyApi,
    ProjectSecretApiKeysListParams,
    PropertyDefinitionsListParams,
    SharingConfigurationApi,
    SubscriptionApi,
    SubscriptionDeliveryApi,
    SubscriptionsDeliveriesListParams,
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

/**
 * Paginated delivery history for a subscription. Requires premium subscriptions.
 * @summary List subscription deliveries
 */
export const getSubscriptionsDeliveriesListUrl = (
    projectId: string,
    subscriptionId: number,
    params?: SubscriptionsDeliveriesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/subscriptions/${subscriptionId}/deliveries/?${stringifiedParams}`
        : `/api/environments/${projectId}/subscriptions/${subscriptionId}/deliveries/`
}

export const subscriptionsDeliveriesList = async (
    projectId: string,
    subscriptionId: number,
    params?: SubscriptionsDeliveriesListParams,
    options?: RequestInit
): Promise<PaginatedSubscriptionDeliveryListApi> => {
    return apiMutator<PaginatedSubscriptionDeliveryListApi>(
        getSubscriptionsDeliveriesListUrl(projectId, subscriptionId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Fetch one delivery row by id.
 * @summary Retrieve subscription delivery
 */
export const getSubscriptionsDeliveriesRetrieveUrl = (projectId: string, subscriptionId: number, id: string) => {
    return `/api/environments/${projectId}/subscriptions/${subscriptionId}/deliveries/${id}/`
}

export const subscriptionsDeliveriesRetrieve = async (
    projectId: string,
    subscriptionId: number,
    id: string,
    options?: RequestInit
): Promise<SubscriptionDeliveryApi> => {
    return apiMutator<SubscriptionDeliveryApi>(getSubscriptionsDeliveriesRetrieveUrl(projectId, subscriptionId, id), {
        ...options,
        method: 'GET',
    })
}

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

/**
 * Create an onboarding delegation invite: an admin-level invite flagged as a setup delegation.
Sends a single dedicated delegation email and records the inviting user as having delegated.
 */
export const getInvitesDelegateCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/invites/delegate/`
}

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

/**
 * ViewSet for listing OAuth applications at the organization level (read-only).
 */
export const getOauthApplicationsListUrl = (organizationId: string, params?: OauthApplicationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/organizations/${organizationId}/oauth_applications/?${stringifiedParams}`
        : `/api/organizations/${organizationId}/oauth_applications/`
}

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

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsListUrl = (organizationId: string, params?: OrganizationsProjectsListParams) => {
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

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/projects/`
}

export const organizationsProjectsCreate = async (
    organizationId: string,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getOrganizationsProjectsCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectBackwardCompatApi),
    })
}

/**
 * Retrieve a project and its settings.
 */
export const getOrganizationsProjectsRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

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

/**
 * Replace a project and its settings. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
export const getOrganizationsProjectsUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

export const organizationsProjectsUpdate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getOrganizationsProjectsUpdateUrl(organizationId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(projectBackwardCompatApi),
    })
}

/**
 * Update one or more of a project's settings. Only the fields included in the request body are changed.
 */
export const getOrganizationsProjectsPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

export const organizationsProjectsPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
    options?: RequestInit
): Promise<ProjectBackwardCompatApi> => {
    return apiMutator<ProjectBackwardCompatApi>(getOrganizationsProjectsPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedProjectBackwardCompatApi),
    })
}

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsDestroyUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/`
}

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

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsActivityRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/activity/`
}

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

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsAddProductIntentPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/add_product_intent/`
}

export const organizationsProjectsAddProductIntentPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
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

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsChangeOrganizationCreateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/change_organization/`
}

export const organizationsProjectsChangeOrganizationCreate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
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

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsCompleteProductOnboardingPartialUpdateUrl = (
    organizationId: string,
    id: number
) => {
    return `/api/organizations/${organizationId}/projects/${id}/complete_product_onboarding/`
}

export const organizationsProjectsCompleteProductOnboardingPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
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

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsDeleteSecretTokenBackupPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/delete_secret_token_backup/`
}

export const organizationsProjectsDeleteSecretTokenBackupPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
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

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsGenerateConversationsPublicTokenCreateUrl = (
    organizationId: string,
    id: number
) => {
    return `/api/organizations/${organizationId}/projects/${id}/generate_conversations_public_token/`
}

export const organizationsProjectsGenerateConversationsPublicTokenCreate = async (
    organizationId: string,
    id: number,
    projectBackwardCompatApi: NonReadonly<ProjectBackwardCompatApi>,
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

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsIsGeneratingDemoDataRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/is_generating_demo_data/`
}

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

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsResetTokenPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/reset_token/`
}

export const organizationsProjectsResetTokenPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
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

/**
 * Projects for the current organization.
 */
export const getOrganizationsProjectsRotateSecretTokenPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/rotate_secret_token/`
}

export const organizationsProjectsRotateSecretTokenPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedProjectBackwardCompatApi: NonReadonly<PatchedProjectBackwardCompatApi>,
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
): Promise<FlagValueResponseApi> => {
    return apiMutator<FlagValueResponseApi>(getFlagValueValuesRetrieveUrl(projectId, params), {
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

export const getProjectSecretApiKeysListUrl = (projectId: string, params?: ProjectSecretApiKeysListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
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
    patchedProjectSecretAPIKeyApi: NonReadonly<PatchedProjectSecretAPIKeyApi>,
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

/**
 * Roll a project secret API key
 */
export const getProjectSecretApiKeysRollCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/project_secret_api_keys/${id}/roll/`
}

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
 * Bulk update tags on multiple objects.

Accepts:
- {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}

Actions:
- "add": Add tags to existing tags on each object
- "remove": Remove specific tags from each object
- "set": Replace all tags on each object with the provided list
 */
export const getPropertyDefinitionsBulkUpdateTagsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/property_definitions/bulk_update_tags/`
}

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

export const getSubscriptionsTestDeliveryCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/subscriptions/${id}/test-delivery/`
}

export const subscriptionsTestDeliveryCreate = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getSubscriptionsTestDeliveryCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
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

/**
 * Retrieve a user's profile and settings. Pass `@me` as the UUID to fetch the authenticated user; non-staff callers may only access their own account.
 */
export const getUsersRetrieveUrl = (uuid: string) => {
    return `/api/users/${uuid}/`
}

export const usersRetrieve = async (uuid: string, options?: RequestInit): Promise<UserApi> => {
    return apiMutator<UserApi>(getUsersRetrieveUrl(uuid), {
        ...options,
        method: 'GET',
    })
}

/**
 * Replace the authenticated user's profile and settings. Pass `@me` as the UUID to update the authenticated user. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
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

/**
 * Update one or more of the authenticated user's profile fields or settings.
 */
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

/**
 * Mark the current user as having exited onboarding with a non-delegated reason.
Idempotent: the skip timestamp is only set on the first successful call.

Callers wanting to delegate setup to a teammate must use the dedicated
/organizations/{id}/invites/delegate/ endpoint, which atomically creates the
invite and sets reason="delegated". This endpoint rejects that reason so state
can't be faked without a real invite.
 */
export const getUsersOnboardingSkipCreateUrl = (uuid: string) => {
    return `/api/users/${uuid}/onboarding/skip/`
}

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
