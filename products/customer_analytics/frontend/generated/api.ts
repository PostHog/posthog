import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    AccountApi,
    AccountNotebookApi,
    AccountsListParams,
    AccountsNotebooksListParams,
    CustomerJourneyApi,
    CustomerJourneysListParams,
    CustomerProfileConfigApi,
    CustomerProfileConfigsListParams,
    GroupUsageMetricApi,
    GroupsTypesMetricsListParams,
    PaginatedAccountListApi,
    PaginatedAccountNotebookListApi,
    PaginatedCustomerJourneyListApi,
    PaginatedCustomerProfileConfigListApi,
    PaginatedGroupUsageMetricListApi,
    PatchedAccountApi,
    PatchedGroupUsageMetricApi,
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

export const getAccountsListUrl = (projectId: string, params?: AccountsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/accounts/?${stringifiedParams}`
        : `/api/environments/${projectId}/accounts/`
}

export const accountsList = async (
    projectId: string,
    params?: AccountsListParams,
    options?: RequestInit
): Promise<PaginatedAccountListApi> => {
    return apiMutator<PaginatedAccountListApi>(getAccountsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAccountsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/accounts/`
}

export const accountsCreate = async (
    projectId: string,
    accountApi: NonReadonly<AccountApi>,
    options?: RequestInit
): Promise<AccountApi> => {
    return apiMutator<AccountApi>(getAccountsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(accountApi),
    })
}

export const getAccountsNotebooksListUrl = (
    projectId: string,
    accountId: string,
    params?: AccountsNotebooksListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/accounts/${accountId}/notebooks/?${stringifiedParams}`
        : `/api/environments/${projectId}/accounts/${accountId}/notebooks/`
}

export const accountsNotebooksList = async (
    projectId: string,
    accountId: string,
    params?: AccountsNotebooksListParams,
    options?: RequestInit
): Promise<PaginatedAccountNotebookListApi> => {
    return apiMutator<PaginatedAccountNotebookListApi>(getAccountsNotebooksListUrl(projectId, accountId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAccountsNotebooksCreateUrl = (projectId: string, accountId: string) => {
    return `/api/environments/${projectId}/accounts/${accountId}/notebooks/`
}

export const accountsNotebooksCreate = async (
    projectId: string,
    accountId: string,
    accountNotebookApi?: NonReadonly<AccountNotebookApi>,
    options?: RequestInit
): Promise<AccountNotebookApi> => {
    return apiMutator<AccountNotebookApi>(getAccountsNotebooksCreateUrl(projectId, accountId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(accountNotebookApi),
    })
}

export const getAccountsNotebooksRetrieveUrl = (projectId: string, accountId: string, shortId: string) => {
    return `/api/environments/${projectId}/accounts/${accountId}/notebooks/${shortId}/`
}

export const accountsNotebooksRetrieve = async (
    projectId: string,
    accountId: string,
    shortId: string,
    options?: RequestInit
): Promise<AccountNotebookApi> => {
    return apiMutator<AccountNotebookApi>(getAccountsNotebooksRetrieveUrl(projectId, accountId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getAccountsNotebooksDestroyUrl = (projectId: string, accountId: string, shortId: string) => {
    return `/api/environments/${projectId}/accounts/${accountId}/notebooks/${shortId}/`
}

export const accountsNotebooksDestroy = async (
    projectId: string,
    accountId: string,
    shortId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAccountsNotebooksDestroyUrl(projectId, accountId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

export const getAccountsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/accounts/${id}/`
}

export const accountsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<AccountApi> => {
    return apiMutator<AccountApi>(getAccountsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAccountsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/accounts/${id}/`
}

export const accountsUpdate = async (
    projectId: string,
    id: string,
    accountApi: NonReadonly<AccountApi>,
    options?: RequestInit
): Promise<AccountApi> => {
    return apiMutator<AccountApi>(getAccountsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(accountApi),
    })
}

export const getAccountsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/accounts/${id}/`
}

export const accountsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedAccountApi?: NonReadonly<PatchedAccountApi>,
    options?: RequestInit
): Promise<AccountApi> => {
    return apiMutator<AccountApi>(getAccountsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedAccountApi),
    })
}

export const getAccountsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/accounts/${id}/`
}

export const accountsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getAccountsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCustomerJourneysListUrl = (projectId: string, params?: CustomerJourneysListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/customer_journeys/?${stringifiedParams}`
        : `/api/environments/${projectId}/customer_journeys/`
}

export const customerJourneysList = async (
    projectId: string,
    params?: CustomerJourneysListParams,
    options?: RequestInit
): Promise<PaginatedCustomerJourneyListApi> => {
    return apiMutator<PaginatedCustomerJourneyListApi>(getCustomerJourneysListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCustomerJourneysCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/customer_journeys/`
}

export const customerJourneysCreate = async (
    projectId: string,
    customerJourneyApi: NonReadonly<CustomerJourneyApi>,
    options?: RequestInit
): Promise<CustomerJourneyApi> => {
    return apiMutator<CustomerJourneyApi>(getCustomerJourneysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customerJourneyApi),
    })
}

export const getCustomerProfileConfigsListUrl = (projectId: string, params?: CustomerProfileConfigsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/customer_profile_configs/?${stringifiedParams}`
        : `/api/environments/${projectId}/customer_profile_configs/`
}

export const customerProfileConfigsList = async (
    projectId: string,
    params?: CustomerProfileConfigsListParams,
    options?: RequestInit
): Promise<PaginatedCustomerProfileConfigListApi> => {
    return apiMutator<PaginatedCustomerProfileConfigListApi>(getCustomerProfileConfigsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCustomerProfileConfigsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/customer_profile_configs/`
}

export const customerProfileConfigsCreate = async (
    projectId: string,
    customerProfileConfigApi: NonReadonly<CustomerProfileConfigApi>,
    options?: RequestInit
): Promise<CustomerProfileConfigApi> => {
    return apiMutator<CustomerProfileConfigApi>(getCustomerProfileConfigsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customerProfileConfigApi),
    })
}

export const getGroupsTypesMetricsListUrl = (
    projectId: string,
    groupTypeIndex: number,
    params?: GroupsTypesMetricsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/`
}

export const groupsTypesMetricsList = async (
    projectId: string,
    groupTypeIndex: number,
    params?: GroupsTypesMetricsListParams,
    options?: RequestInit
): Promise<PaginatedGroupUsageMetricListApi> => {
    return apiMutator<PaginatedGroupUsageMetricListApi>(
        getGroupsTypesMetricsListUrl(projectId, groupTypeIndex, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getGroupsTypesMetricsCreateUrl = (projectId: string, groupTypeIndex: number) => {
    return `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/`
}

export const groupsTypesMetricsCreate = async (
    projectId: string,
    groupTypeIndex: number,
    groupUsageMetricApi: NonReadonly<GroupUsageMetricApi>,
    options?: RequestInit
): Promise<GroupUsageMetricApi> => {
    return apiMutator<GroupUsageMetricApi>(getGroupsTypesMetricsCreateUrl(projectId, groupTypeIndex), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupUsageMetricApi),
    })
}

export const getGroupsTypesMetricsRetrieveUrl = (projectId: string, groupTypeIndex: number, id: string) => {
    return `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/${id}/`
}

export const groupsTypesMetricsRetrieve = async (
    projectId: string,
    groupTypeIndex: number,
    id: string,
    options?: RequestInit
): Promise<GroupUsageMetricApi> => {
    return apiMutator<GroupUsageMetricApi>(getGroupsTypesMetricsRetrieveUrl(projectId, groupTypeIndex, id), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsTypesMetricsUpdateUrl = (projectId: string, groupTypeIndex: number, id: string) => {
    return `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/${id}/`
}

export const groupsTypesMetricsUpdate = async (
    projectId: string,
    groupTypeIndex: number,
    id: string,
    groupUsageMetricApi: NonReadonly<GroupUsageMetricApi>,
    options?: RequestInit
): Promise<GroupUsageMetricApi> => {
    return apiMutator<GroupUsageMetricApi>(getGroupsTypesMetricsUpdateUrl(projectId, groupTypeIndex, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupUsageMetricApi),
    })
}

export const getGroupsTypesMetricsPartialUpdateUrl = (projectId: string, groupTypeIndex: number, id: string) => {
    return `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/${id}/`
}

export const groupsTypesMetricsPartialUpdate = async (
    projectId: string,
    groupTypeIndex: number,
    id: string,
    patchedGroupUsageMetricApi?: NonReadonly<PatchedGroupUsageMetricApi>,
    options?: RequestInit
): Promise<GroupUsageMetricApi> => {
    return apiMutator<GroupUsageMetricApi>(getGroupsTypesMetricsPartialUpdateUrl(projectId, groupTypeIndex, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedGroupUsageMetricApi),
    })
}

export const getGroupsTypesMetricsDestroyUrl = (projectId: string, groupTypeIndex: number, id: string) => {
    return `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/${id}/`
}

export const groupsTypesMetricsDestroy = async (
    projectId: string,
    groupTypeIndex: number,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsTypesMetricsDestroyUrl(projectId, groupTypeIndex, id), {
        ...options,
        method: 'DELETE',
    })
}
