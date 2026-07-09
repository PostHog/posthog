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
    AccountNotesListParams,
    AccountRelationshipApi,
    AccountRelationshipDefinitionApi,
    AccountRelationshipDefinitionsListParams,
    AccountRelationshipWriteApi,
    AccountsListParams,
    AccountsNotebooksListParams,
    AccountsRelationshipsListParams,
    CustomPropertyDefinitionApi,
    CustomPropertyDefinitionsListParams,
    CustomPropertyDefinitionsValuesRetrieveParams,
    CustomPropertySourceApi,
    CustomPropertySourceUpdateApi,
    CustomPropertySourcesListParams,
    CustomPropertyValueApi,
    CustomPropertyValueSuggestionsResponseApi,
    CustomPropertyValueWriteApi,
    CustomerJourneyApi,
    CustomerJourneysListParams,
    CustomerProfileConfigApi,
    CustomerProfileConfigsListParams,
    EventStreamApi,
    EventStreamMemberWriteApi,
    EventStreamTestMessageApi,
    GroupUsageMetricApi,
    GroupsTypesMetricsListParams,
    PaginatedAccountListApi,
    PaginatedAccountNoteListApi,
    PaginatedAccountNotebookListApi,
    PaginatedAccountRelationshipDefinitionListApi,
    PaginatedCustomPropertyDefinitionListApi,
    PaginatedCustomPropertySourceListApi,
    PaginatedCustomerJourneyListApi,
    PaginatedCustomerProfileConfigListApi,
    PaginatedGroupUsageMetricListApi,
    PatchedAccountApi,
    PatchedAccountRelationshipDefinitionApi,
    PatchedCustomPropertyDefinitionApi,
    PatchedCustomPropertySourceUpdateApi,
    PatchedCustomerJourneyApi,
    PatchedCustomerProfileConfigApi,
    PatchedEventStreamApi,
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

export const getAccountNotesListUrl = (projectId: string, params?: AccountNotesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/account_notes/?${stringifiedParams}`
        : `/api/projects/${projectId}/account_notes/`
}

export const accountNotesList = async (
    projectId: string,
    params?: AccountNotesListParams,
    options?: RequestInit
): Promise<PaginatedAccountNoteListApi> => {
    return apiMutator<PaginatedAccountNoteListApi>(getAccountNotesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAccountRelationshipDefinitionsListUrl = (
    projectId: string,
    params?: AccountRelationshipDefinitionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/account_relationship_definitions/?${stringifiedParams}`
        : `/api/projects/${projectId}/account_relationship_definitions/`
}

export const accountRelationshipDefinitionsList = async (
    projectId: string,
    params?: AccountRelationshipDefinitionsListParams,
    options?: RequestInit
): Promise<PaginatedAccountRelationshipDefinitionListApi> => {
    return apiMutator<PaginatedAccountRelationshipDefinitionListApi>(
        getAccountRelationshipDefinitionsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAccountRelationshipDefinitionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/account_relationship_definitions/`
}

export const accountRelationshipDefinitionsCreate = async (
    projectId: string,
    accountRelationshipDefinitionApi: NonReadonly<AccountRelationshipDefinitionApi>,
    options?: RequestInit
): Promise<AccountRelationshipDefinitionApi> => {
    return apiMutator<AccountRelationshipDefinitionApi>(getAccountRelationshipDefinitionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(accountRelationshipDefinitionApi),
    })
}

export const getAccountRelationshipDefinitionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/account_relationship_definitions/${id}/`
}

export const accountRelationshipDefinitionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<AccountRelationshipDefinitionApi> => {
    return apiMutator<AccountRelationshipDefinitionApi>(getAccountRelationshipDefinitionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAccountRelationshipDefinitionsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/account_relationship_definitions/${id}/`
}

export const accountRelationshipDefinitionsUpdate = async (
    projectId: string,
    id: string,
    accountRelationshipDefinitionApi: NonReadonly<AccountRelationshipDefinitionApi>,
    options?: RequestInit
): Promise<AccountRelationshipDefinitionApi> => {
    return apiMutator<AccountRelationshipDefinitionApi>(getAccountRelationshipDefinitionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(accountRelationshipDefinitionApi),
    })
}

export const getAccountRelationshipDefinitionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/account_relationship_definitions/${id}/`
}

export const accountRelationshipDefinitionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedAccountRelationshipDefinitionApi?: NonReadonly<PatchedAccountRelationshipDefinitionApi>,
    options?: RequestInit
): Promise<AccountRelationshipDefinitionApi> => {
    return apiMutator<AccountRelationshipDefinitionApi>(
        getAccountRelationshipDefinitionsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedAccountRelationshipDefinitionApi),
        }
    )
}

export const getAccountRelationshipDefinitionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/account_relationship_definitions/${id}/`
}

export const accountRelationshipDefinitionsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getAccountRelationshipDefinitionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getAccountsListUrl = (projectId: string, params?: AccountsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/accounts/?${stringifiedParams}`
        : `/api/projects/${projectId}/accounts/`
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
    return `/api/projects/${projectId}/accounts/`
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

export const getAccountsCustomPropertyValuesListUrl = (projectId: string, accountId: string) => {
    return `/api/projects/${projectId}/accounts/${accountId}/custom_property_values/`
}

export const accountsCustomPropertyValuesList = async (
    projectId: string,
    accountId: string,
    options?: RequestInit
): Promise<CustomPropertyValueApi[]> => {
    return apiMutator<CustomPropertyValueApi[]>(getAccountsCustomPropertyValuesListUrl(projectId, accountId), {
        ...options,
        method: 'GET',
    })
}

export const getAccountsCustomPropertyValuesCreateUrl = (projectId: string, accountId: string) => {
    return `/api/projects/${projectId}/accounts/${accountId}/custom_property_values/`
}

export const accountsCustomPropertyValuesCreate = async (
    projectId: string,
    accountId: string,
    customPropertyValueWriteApi: CustomPropertyValueWriteApi,
    options?: RequestInit
): Promise<CustomPropertyValueApi> => {
    return apiMutator<CustomPropertyValueApi>(getAccountsCustomPropertyValuesCreateUrl(projectId, accountId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customPropertyValueWriteApi),
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/accounts/${accountId}/notebooks/?${stringifiedParams}`
        : `/api/projects/${projectId}/accounts/${accountId}/notebooks/`
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
    return `/api/projects/${projectId}/accounts/${accountId}/notebooks/`
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
    return `/api/projects/${projectId}/accounts/${accountId}/notebooks/${shortId}/`
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
    return `/api/projects/${projectId}/accounts/${accountId}/notebooks/${shortId}/`
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

export const getAccountsRelationshipsListUrl = (
    projectId: string,
    accountId: string,
    params?: AccountsRelationshipsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/accounts/${accountId}/relationships/?${stringifiedParams}`
        : `/api/projects/${projectId}/accounts/${accountId}/relationships/`
}

export const accountsRelationshipsList = async (
    projectId: string,
    accountId: string,
    params?: AccountsRelationshipsListParams,
    options?: RequestInit
): Promise<AccountRelationshipApi[]> => {
    return apiMutator<AccountRelationshipApi[]>(getAccountsRelationshipsListUrl(projectId, accountId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAccountsRelationshipsCreateUrl = (projectId: string, accountId: string) => {
    return `/api/projects/${projectId}/accounts/${accountId}/relationships/`
}

export const accountsRelationshipsCreate = async (
    projectId: string,
    accountId: string,
    accountRelationshipWriteApi: AccountRelationshipWriteApi,
    options?: RequestInit
): Promise<AccountRelationshipApi> => {
    return apiMutator<AccountRelationshipApi>(getAccountsRelationshipsCreateUrl(projectId, accountId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(accountRelationshipWriteApi),
    })
}

export const getAccountsRelationshipsEndCreateUrl = (projectId: string, accountId: string, id: string) => {
    return `/api/projects/${projectId}/accounts/${accountId}/relationships/${id}/end/`
}

export const accountsRelationshipsEndCreate = async (
    projectId: string,
    accountId: string,
    id: string,
    options?: RequestInit
): Promise<AccountRelationshipApi> => {
    return apiMutator<AccountRelationshipApi>(getAccountsRelationshipsEndCreateUrl(projectId, accountId, id), {
        ...options,
        method: 'POST',
    })
}

export const getAccountsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/accounts/${id}/`
}

export const accountsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<AccountApi> => {
    return apiMutator<AccountApi>(getAccountsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAccountsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/accounts/${id}/`
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
    return `/api/projects/${projectId}/accounts/${id}/`
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
    return `/api/projects/${projectId}/accounts/${id}/`
}

export const accountsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getAccountsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCustomPropertyDefinitionsListUrl = (
    projectId: string,
    params?: CustomPropertyDefinitionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/custom_property_definitions/?${stringifiedParams}`
        : `/api/projects/${projectId}/custom_property_definitions/`
}

export const customPropertyDefinitionsList = async (
    projectId: string,
    params?: CustomPropertyDefinitionsListParams,
    options?: RequestInit
): Promise<PaginatedCustomPropertyDefinitionListApi> => {
    return apiMutator<PaginatedCustomPropertyDefinitionListApi>(
        getCustomPropertyDefinitionsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCustomPropertyDefinitionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/custom_property_definitions/`
}

export const customPropertyDefinitionsCreate = async (
    projectId: string,
    customPropertyDefinitionApi: NonReadonly<CustomPropertyDefinitionApi>,
    options?: RequestInit
): Promise<CustomPropertyDefinitionApi> => {
    return apiMutator<CustomPropertyDefinitionApi>(getCustomPropertyDefinitionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customPropertyDefinitionApi),
    })
}

export const getCustomPropertyDefinitionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/custom_property_definitions/${id}/`
}

export const customPropertyDefinitionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CustomPropertyDefinitionApi> => {
    return apiMutator<CustomPropertyDefinitionApi>(getCustomPropertyDefinitionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCustomPropertyDefinitionsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/custom_property_definitions/${id}/`
}

export const customPropertyDefinitionsUpdate = async (
    projectId: string,
    id: string,
    customPropertyDefinitionApi: NonReadonly<CustomPropertyDefinitionApi>,
    options?: RequestInit
): Promise<CustomPropertyDefinitionApi> => {
    return apiMutator<CustomPropertyDefinitionApi>(getCustomPropertyDefinitionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customPropertyDefinitionApi),
    })
}

export const getCustomPropertyDefinitionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/custom_property_definitions/${id}/`
}

export const customPropertyDefinitionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCustomPropertyDefinitionApi?: NonReadonly<PatchedCustomPropertyDefinitionApi>,
    options?: RequestInit
): Promise<CustomPropertyDefinitionApi> => {
    return apiMutator<CustomPropertyDefinitionApi>(getCustomPropertyDefinitionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCustomPropertyDefinitionApi),
    })
}

export const getCustomPropertyDefinitionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/custom_property_definitions/${id}/`
}

export const customPropertyDefinitionsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCustomPropertyDefinitionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCustomPropertyDefinitionsValuesRetrieveUrl = (
    projectId: string,
    params: CustomPropertyDefinitionsValuesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/custom_property_definitions/values/?${stringifiedParams}`
        : `/api/projects/${projectId}/custom_property_definitions/values/`
}

export const customPropertyDefinitionsValuesRetrieve = async (
    projectId: string,
    params: CustomPropertyDefinitionsValuesRetrieveParams,
    options?: RequestInit
): Promise<CustomPropertyValueSuggestionsResponseApi> => {
    return apiMutator<CustomPropertyValueSuggestionsResponseApi>(
        getCustomPropertyDefinitionsValuesRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCustomPropertySourcesListUrl = (projectId: string, params?: CustomPropertySourcesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/custom_property_sources/?${stringifiedParams}`
        : `/api/projects/${projectId}/custom_property_sources/`
}

export const customPropertySourcesList = async (
    projectId: string,
    params?: CustomPropertySourcesListParams,
    options?: RequestInit
): Promise<PaginatedCustomPropertySourceListApi> => {
    return apiMutator<PaginatedCustomPropertySourceListApi>(getCustomPropertySourcesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCustomPropertySourcesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/custom_property_sources/`
}

export const customPropertySourcesCreate = async (
    projectId: string,
    customPropertySourceApi: NonReadonly<CustomPropertySourceApi>,
    options?: RequestInit
): Promise<CustomPropertySourceApi> => {
    return apiMutator<CustomPropertySourceApi>(getCustomPropertySourcesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customPropertySourceApi),
    })
}

export const getCustomPropertySourcesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/custom_property_sources/${id}/`
}

export const customPropertySourcesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CustomPropertySourceApi> => {
    return apiMutator<CustomPropertySourceApi>(getCustomPropertySourcesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCustomPropertySourcesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/custom_property_sources/${id}/`
}

export const customPropertySourcesUpdate = async (
    projectId: string,
    id: string,
    customPropertySourceUpdateApi?: CustomPropertySourceUpdateApi,
    options?: RequestInit
): Promise<CustomPropertySourceApi> => {
    return apiMutator<CustomPropertySourceApi>(getCustomPropertySourcesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customPropertySourceUpdateApi),
    })
}

export const getCustomPropertySourcesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/custom_property_sources/${id}/`
}

export const customPropertySourcesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCustomPropertySourceUpdateApi?: PatchedCustomPropertySourceUpdateApi,
    options?: RequestInit
): Promise<CustomPropertySourceApi> => {
    return apiMutator<CustomPropertySourceApi>(getCustomPropertySourcesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCustomPropertySourceUpdateApi),
    })
}

export const getCustomPropertySourcesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/custom_property_sources/${id}/`
}

export const customPropertySourcesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCustomPropertySourcesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCustomerJourneysListUrl = (projectId: string, params?: CustomerJourneysListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/customer_journeys/?${stringifiedParams}`
        : `/api/projects/${projectId}/customer_journeys/`
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
    return `/api/projects/${projectId}/customer_journeys/`
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

export const getCustomerJourneysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/customer_journeys/${id}/`
}

export const customerJourneysRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CustomerJourneyApi> => {
    return apiMutator<CustomerJourneyApi>(getCustomerJourneysRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCustomerJourneysUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/customer_journeys/${id}/`
}

export const customerJourneysUpdate = async (
    projectId: string,
    id: string,
    customerJourneyApi: NonReadonly<CustomerJourneyApi>,
    options?: RequestInit
): Promise<CustomerJourneyApi> => {
    return apiMutator<CustomerJourneyApi>(getCustomerJourneysUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customerJourneyApi),
    })
}

export const getCustomerJourneysPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/customer_journeys/${id}/`
}

export const customerJourneysPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCustomerJourneyApi?: NonReadonly<PatchedCustomerJourneyApi>,
    options?: RequestInit
): Promise<CustomerJourneyApi> => {
    return apiMutator<CustomerJourneyApi>(getCustomerJourneysPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCustomerJourneyApi),
    })
}

export const getCustomerJourneysDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/customer_journeys/${id}/`
}

export const customerJourneysDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getCustomerJourneysDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCustomerProfileConfigsListUrl = (projectId: string, params?: CustomerProfileConfigsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/customer_profile_configs/?${stringifiedParams}`
        : `/api/projects/${projectId}/customer_profile_configs/`
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
    return `/api/projects/${projectId}/customer_profile_configs/`
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

export const getCustomerProfileConfigsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/customer_profile_configs/${id}/`
}

export const customerProfileConfigsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CustomerProfileConfigApi> => {
    return apiMutator<CustomerProfileConfigApi>(getCustomerProfileConfigsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCustomerProfileConfigsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/customer_profile_configs/${id}/`
}

export const customerProfileConfigsUpdate = async (
    projectId: string,
    id: string,
    customerProfileConfigApi: NonReadonly<CustomerProfileConfigApi>,
    options?: RequestInit
): Promise<CustomerProfileConfigApi> => {
    return apiMutator<CustomerProfileConfigApi>(getCustomerProfileConfigsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customerProfileConfigApi),
    })
}

export const getCustomerProfileConfigsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/customer_profile_configs/${id}/`
}

export const customerProfileConfigsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCustomerProfileConfigApi?: NonReadonly<PatchedCustomerProfileConfigApi>,
    options?: RequestInit
): Promise<CustomerProfileConfigApi> => {
    return apiMutator<CustomerProfileConfigApi>(getCustomerProfileConfigsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedCustomerProfileConfigApi),
    })
}

export const getCustomerProfileConfigsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/customer_profile_configs/${id}/`
}

export const customerProfileConfigsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCustomerProfileConfigsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEventStreamsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_streams/`
}

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const eventStreamsList = async (projectId: string, options?: RequestInit): Promise<EventStreamApi[]> => {
    return apiMutator<EventStreamApi[]>(getEventStreamsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEventStreamsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_streams/`
}

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const eventStreamsCreate = async (
    projectId: string,
    eventStreamApi?: NonReadonly<EventStreamApi>,
    options?: RequestInit
): Promise<EventStreamApi> => {
    return apiMutator<EventStreamApi>(getEventStreamsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(eventStreamApi),
    })
}

export const getEventStreamsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_streams/${id}/`
}

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const eventStreamsUpdate = async (
    projectId: string,
    id: string,
    eventStreamApi?: NonReadonly<EventStreamApi>,
    options?: RequestInit
): Promise<EventStreamApi> => {
    return apiMutator<EventStreamApi>(getEventStreamsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(eventStreamApi),
    })
}

export const getEventStreamsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_streams/${id}/`
}

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const eventStreamsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedEventStreamApi?: NonReadonly<PatchedEventStreamApi>,
    options?: RequestInit
): Promise<EventStreamApi> => {
    return apiMutator<EventStreamApi>(getEventStreamsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEventStreamApi),
    })
}

export const getEventStreamsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_streams/${id}/`
}

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const eventStreamsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEventStreamsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEventStreamsAddAccountCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_streams/${id}/add_account/`
}

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const eventStreamsAddAccountCreate = async (
    projectId: string,
    id: string,
    eventStreamMemberWriteApi: EventStreamMemberWriteApi,
    options?: RequestInit
): Promise<EventStreamApi> => {
    return apiMutator<EventStreamApi>(getEventStreamsAddAccountCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(eventStreamMemberWriteApi),
    })
}

export const getEventStreamsRemoveAccountCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_streams/${id}/remove_account/`
}

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const eventStreamsRemoveAccountCreate = async (
    projectId: string,
    id: string,
    eventStreamMemberWriteApi: EventStreamMemberWriteApi,
    options?: RequestInit
): Promise<EventStreamApi> => {
    return apiMutator<EventStreamApi>(getEventStreamsRemoveAccountCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(eventStreamMemberWriteApi),
    })
}

export const getEventStreamsSendTestMessageCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_streams/${id}/send_test_message/`
}

/**
 * The caller's event stream: a live feed of selected accounts' events posted to a
 * Slack channel of their choice. Per-user — each team member owns at most one stream, and
 * every endpoint is scoped to the caller's own. Delivery runs through a managed CDP
 * destination that is re-provisioned inside the same transaction as every write, so
 * config and delivery can't drift apart.
 */
export const eventStreamsSendTestMessageCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<EventStreamTestMessageApi> => {
    return apiMutator<EventStreamTestMessageApi>(getEventStreamsSendTestMessageCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
