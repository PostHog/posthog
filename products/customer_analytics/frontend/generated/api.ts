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
    AccountTrackRulePreviewApi,
    AccountTrackRuleRunRequestApi,
    AccountTrackRuleRunViewApi,
    AccountTrackRulesConfigApi,
    AccountTrackRulesRunsListParams,
    AccountsEmailThreadMessagesListParams,
    AccountsEmailThreadsListParams,
    AccountsListParams,
    AccountsMeetingsListParams,
    AccountsNotebooksListParams,
    AccountsRelationshipsListParams,
    AccountsSummariesListParams,
    AccountsSupportTicketMessagesListParams,
    AnnouncementApi,
    AnnouncementChannelApi,
    AnnouncementsListParams,
    CalendarSyncStatusApi,
    CalendarSyncTriggerApi,
    CalendarSyncTriggerResponseApi,
    CustomPropertyDefinitionApi,
    CustomPropertyDefinitionsListParams,
    CustomPropertyDefinitionsValuesRetrieveParams,
    CustomPropertySourceApi,
    CustomPropertySourceUpdateApi,
    CustomPropertySourcesListParams,
    CustomPropertySourcesRunsListParams,
    CustomPropertySyncTriggerResponseApi,
    CustomPropertyValueApi,
    CustomPropertyValueSuggestionsResponseApi,
    CustomPropertyValueWriteApi,
    CustomerAnalyticsExternalAccountsRetrieveParams,
    CustomerJourneyApi,
    CustomerJourneysListParams,
    CustomerProfileConfigApi,
    CustomerProfileConfigsListParams,
    EventStreamApi,
    EventStreamMemberWriteApi,
    EventStreamTestMessageApi,
    ExternalAccountListPageApi,
    FeatureRequestAddAccountApi,
    FeatureRequestApi,
    FeatureRequestCreateApi,
    FeatureRequestEvidenceCreateApi,
    FeatureRequestEvidenceDeleteApi,
    FeatureRequestEvidenceUpdateApi,
    FeatureRequestHistoryApi,
    FeatureRequestProductAreaApi,
    FeatureRequestProductAreasListParams,
    FeatureRequestStatusHistoryApi,
    FeatureRequestUpdateApi,
    FeatureRequestVersionApi,
    FeatureRequestsListParams,
    GroupUsageMetricApi,
    GroupsTypesMetricsListParams,
    PaginatedAccountChannelSummaryListApi,
    PaginatedAccountEmailThreadListApi,
    PaginatedAccountEmailThreadMessageListApi,
    PaginatedAccountListApi,
    PaginatedAccountNoteListApi,
    PaginatedAccountNotebookListApi,
    PaginatedAccountRelationshipDefinitionListApi,
    PaginatedAccountSupportTicketMessageListApi,
    PaginatedAccountTrackRuleRunViewListApi,
    PaginatedAnnouncementListApi,
    PaginatedCustomPropertyDefinitionListApi,
    PaginatedCustomPropertySourceListApi,
    PaginatedCustomPropertySyncRunListApi,
    PaginatedCustomerJourneyListApi,
    PaginatedCustomerProfileConfigListApi,
    PaginatedFeatureRequestListApi,
    PaginatedGroupUsageMetricListApi,
    PaginatedMeetingListApi,
    PatchedAccountApi,
    PatchedAccountRelationshipDefinitionApi,
    PatchedCustomPropertyDefinitionApi,
    PatchedCustomPropertySourceUpdateApi,
    PatchedCustomerJourneyApi,
    PatchedCustomerProfileConfigApi,
    PatchedEventStreamApi,
    PatchedFeatureRequestProductAreaApi,
    PatchedFeatureRequestUpdateApi,
    PatchedGroupUsageMetricApi,
    SupportTicketApi,
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

export const getCustomerAnalyticsExternalAccountsRetrieveUrl = (
    params?: CustomerAnalyticsExternalAccountsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/customer_analytics/external/accounts?${stringifiedParams}`
        : `/api/customer_analytics/external/accounts`
}

/**
 * List tracked accounts with external IDs, lifecycle timestamps, and active relationship assignments. Set `include_ignored=true` to include ignored accounts. Requires a project secret API key with the `account:read` scope.
 * @summary List external customer analytics accounts
 */
export const customerAnalyticsExternalAccountsRetrieve = async (
    params?: CustomerAnalyticsExternalAccountsRetrieveParams,
    options?: RequestInit
): Promise<ExternalAccountListPageApi> => {
    return apiMutator<ExternalAccountListPageApi>(getCustomerAnalyticsExternalAccountsRetrieveUrl(params), {
        ...options,
        method: 'GET',
    })
}

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

export const getAccountTrackRulesListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/account_track_rules/`
}

export const accountTrackRulesList = async (
    projectId: string,
    options?: RequestInit
): Promise<AccountTrackRulesConfigApi> => {
    return apiMutator<AccountTrackRulesConfigApi>(getAccountTrackRulesListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getAccountTrackRulesUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/account_track_rules/`
}

export const accountTrackRulesUpdate = async (
    projectId: string,
    accountTrackRulesConfigApi: AccountTrackRulesConfigApi,
    options?: RequestInit
): Promise<AccountTrackRulesConfigApi> => {
    return apiMutator<AccountTrackRulesConfigApi>(getAccountTrackRulesUpdateUrl(projectId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(accountTrackRulesConfigApi),
    })
}

export const getAccountTrackRulesPreviewCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/account_track_rules/preview/`
}

export const accountTrackRulesPreviewCreate = async (
    projectId: string,
    accountTrackRulesConfigApi: AccountTrackRulesConfigApi,
    options?: RequestInit
): Promise<AccountTrackRulePreviewApi> => {
    return apiMutator<AccountTrackRulePreviewApi>(getAccountTrackRulesPreviewCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(accountTrackRulesConfigApi),
    })
}

export const getAccountTrackRulesRunCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/account_track_rules/run/`
}

export const accountTrackRulesRunCreate = async (
    projectId: string,
    accountTrackRuleRunRequestApi: AccountTrackRuleRunRequestApi,
    options?: RequestInit
): Promise<AccountTrackRuleRunViewApi> => {
    return apiMutator<AccountTrackRuleRunViewApi>(getAccountTrackRulesRunCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(accountTrackRuleRunRequestApi),
    })
}

export const getAccountTrackRulesRunsListUrl = (projectId: string, params?: AccountTrackRulesRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/account_track_rules/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/account_track_rules/runs/`
}

export const accountTrackRulesRunsList = async (
    projectId: string,
    params?: AccountTrackRulesRunsListParams,
    options?: RequestInit
): Promise<PaginatedAccountTrackRuleRunViewListApi> => {
    return apiMutator<PaginatedAccountTrackRuleRunViewListApi>(getAccountTrackRulesRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
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

export const getAccountsEmailThreadsListUrl = (
    projectId: string,
    id: string,
    params?: AccountsEmailThreadsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/accounts/${id}/email_threads/?${stringifiedParams}`
        : `/api/projects/${projectId}/accounts/${id}/email_threads/`
}

export const accountsEmailThreadsList = async (
    projectId: string,
    id: string,
    params?: AccountsEmailThreadsListParams,
    options?: RequestInit
): Promise<PaginatedAccountEmailThreadListApi> => {
    return apiMutator<PaginatedAccountEmailThreadListApi>(getAccountsEmailThreadsListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getAccountsEmailThreadMessagesListUrl = (
    projectId: string,
    id: string,
    threadId: string,
    params?: AccountsEmailThreadMessagesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/accounts/${id}/email_threads/${threadId}/?${stringifiedParams}`
        : `/api/projects/${projectId}/accounts/${id}/email_threads/${threadId}/`
}

export const accountsEmailThreadMessagesList = async (
    projectId: string,
    id: string,
    threadId: string,
    params?: AccountsEmailThreadMessagesListParams,
    options?: RequestInit
): Promise<PaginatedAccountEmailThreadMessageListApi> => {
    return apiMutator<PaginatedAccountEmailThreadMessageListApi>(
        getAccountsEmailThreadMessagesListUrl(projectId, id, threadId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAccountsMeetingsListUrl = (projectId: string, id: string, params?: AccountsMeetingsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/accounts/${id}/meetings/?${stringifiedParams}`
        : `/api/projects/${projectId}/accounts/${id}/meetings/`
}

export const accountsMeetingsList = async (
    projectId: string,
    id: string,
    params?: AccountsMeetingsListParams,
    options?: RequestInit
): Promise<PaginatedMeetingListApi> => {
    return apiMutator<PaginatedMeetingListApi>(getAccountsMeetingsListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getAccountsSummariesListUrl = (projectId: string, id: string, params?: AccountsSummariesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/accounts/${id}/summaries/?${stringifiedParams}`
        : `/api/projects/${projectId}/accounts/${id}/summaries/`
}

export const accountsSummariesList = async (
    projectId: string,
    id: string,
    params?: AccountsSummariesListParams,
    options?: RequestInit
): Promise<PaginatedAccountChannelSummaryListApi> => {
    return apiMutator<PaginatedAccountChannelSummaryListApi>(getAccountsSummariesListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getAccountsSupportTicketsListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/accounts/${id}/support_tickets/`
}

export const accountsSupportTicketsList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SupportTicketApi[]> => {
    return apiMutator<SupportTicketApi[]>(getAccountsSupportTicketsListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getAccountsSupportTicketMessagesListUrl = (
    projectId: string,
    id: string,
    ticketId: string,
    params?: AccountsSupportTicketMessagesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/accounts/${id}/support_tickets/${ticketId}/?${stringifiedParams}`
        : `/api/projects/${projectId}/accounts/${id}/support_tickets/${ticketId}/`
}

export const accountsSupportTicketMessagesList = async (
    projectId: string,
    id: string,
    ticketId: string,
    params?: AccountsSupportTicketMessagesListParams,
    options?: RequestInit
): Promise<PaginatedAccountSupportTicketMessageListApi> => {
    return apiMutator<PaginatedAccountSupportTicketMessageListApi>(
        getAccountsSupportTicketMessagesListUrl(projectId, id, ticketId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getAnnouncementsListUrl = (projectId: string, params?: AnnouncementsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/announcements/?${stringifiedParams}`
        : `/api/projects/${projectId}/announcements/`
}

export const announcementsList = async (
    projectId: string,
    params?: AnnouncementsListParams,
    options?: RequestInit
): Promise<PaginatedAnnouncementListApi> => {
    return apiMutator<PaginatedAnnouncementListApi>(getAnnouncementsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getAnnouncementsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/announcements/`
}

export const announcementsCreate = async (
    projectId: string,
    announcementApi: NonReadonly<AnnouncementApi>,
    options?: RequestInit
): Promise<AnnouncementApi> => {
    return apiMutator<AnnouncementApi>(getAnnouncementsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(announcementApi),
    })
}

export const getAnnouncementsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/announcements/${shortId}/`
}

export const announcementsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<AnnouncementApi> => {
    return apiMutator<AnnouncementApi>(getAnnouncementsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getAnnouncementsChannelsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/announcements/channels/`
}

/**
 * Slack channels the SupportHog bot can post to, labeled by customer account name.
 */
export const announcementsChannelsList = async (
    projectId: string,
    options?: RequestInit
): Promise<AnnouncementChannelApi[]> => {
    return apiMutator<AnnouncementChannelApi[]>(getAnnouncementsChannelsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getCalendarSyncListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/calendar_sync/`
}

/**
 * Calendar-sync controls for Customer analytics settings. Sync runs on an hourly
 * Temporal schedule; this surface only offers the manual "sync now" escape hatch.
 */
export const calendarSyncList = async (projectId: string, options?: RequestInit): Promise<CalendarSyncStatusApi[]> => {
    return apiMutator<CalendarSyncStatusApi[]>(getCalendarSyncListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getCalendarSyncSyncNowCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/calendar_sync/sync_now/`
}

/**
 * Start a sync run for one connected Google Calendar immediately, outside the hourly schedule.
 * @summary Sync a connected calendar now
 */
export const calendarSyncSyncNowCreate = async (
    projectId: string,
    calendarSyncTriggerApi: CalendarSyncTriggerApi,
    options?: RequestInit
): Promise<CalendarSyncTriggerResponseApi> => {
    return apiMutator<CalendarSyncTriggerResponseApi>(getCalendarSyncSyncNowCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(calendarSyncTriggerApi),
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

export const getCustomPropertySourcesBackfillUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/custom_property_sources/${id}/backfill/`
}

/**
 * Person and group sources only: start a backfill that reads the whole warehouse table and
 * populates person or group properties for historical rows. Coalesces if one is already running
 * for the table.
 */
export const customPropertySourcesBackfill = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CustomPropertySyncTriggerResponseApi> => {
    return apiMutator<CustomPropertySyncTriggerResponseApi>(getCustomPropertySourcesBackfillUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getCustomPropertySourcesRunsListUrl = (
    projectId: string,
    id: string,
    params?: CustomPropertySourcesRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/custom_property_sources/${id}/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/custom_property_sources/${id}/runs/`
}

/**
 * Person and group sources only: the source's sync/backfill run history, newest first. Gated
 * on the caller's warehouse-source viewer access, since the runs expose its row counts and sync
 * errors.
 */
export const customPropertySourcesRunsList = async (
    projectId: string,
    id: string,
    params?: CustomPropertySourcesRunsListParams,
    options?: RequestInit
): Promise<PaginatedCustomPropertySyncRunListApi> => {
    return apiMutator<PaginatedCustomPropertySyncRunListApi>(
        getCustomPropertySourcesRunsListUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCustomPropertySourcesSyncUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/custom_property_sources/${id}/sync/`
}

/**
 * Person and group sources only: run what this source reads now — an import for a table
 * binding (a real, billable warehouse sync), a materialization for a view binding. The
 * incremental person/group-property update runs off that run.
 */
export const customPropertySourcesSync = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CustomPropertySyncTriggerResponseApi> => {
    return apiMutator<CustomPropertySyncTriggerResponseApi>(getCustomPropertySourcesSyncUrl(projectId, id), {
        ...options,
        method: 'POST',
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

export const getFeatureRequestProductAreasListUrl = (
    projectId: string,
    params?: FeatureRequestProductAreasListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_request_product_areas/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_request_product_areas/`
}

export const featureRequestProductAreasList = async (
    projectId: string,
    params?: FeatureRequestProductAreasListParams,
    options?: RequestInit
): Promise<FeatureRequestProductAreaApi[]> => {
    return apiMutator<FeatureRequestProductAreaApi[]>(getFeatureRequestProductAreasListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getFeatureRequestProductAreasCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_request_product_areas/`
}

export const featureRequestProductAreasCreate = async (
    projectId: string,
    featureRequestProductAreaApi: NonReadonly<FeatureRequestProductAreaApi>,
    options?: RequestInit
): Promise<FeatureRequestProductAreaApi> => {
    return apiMutator<FeatureRequestProductAreaApi>(getFeatureRequestProductAreasCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureRequestProductAreaApi),
    })
}

export const getFeatureRequestProductAreasUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_request_product_areas/${id}/`
}

export const featureRequestProductAreasUpdate = async (
    projectId: string,
    id: string,
    featureRequestProductAreaApi: NonReadonly<FeatureRequestProductAreaApi>,
    options?: RequestInit
): Promise<FeatureRequestProductAreaApi> => {
    return apiMutator<FeatureRequestProductAreaApi>(getFeatureRequestProductAreasUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureRequestProductAreaApi),
    })
}

export const getFeatureRequestProductAreasPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_request_product_areas/${id}/`
}

export const featureRequestProductAreasPartialUpdate = async (
    projectId: string,
    id: string,
    patchedFeatureRequestProductAreaApi?: NonReadonly<PatchedFeatureRequestProductAreaApi>,
    options?: RequestInit
): Promise<FeatureRequestProductAreaApi> => {
    return apiMutator<FeatureRequestProductAreaApi>(getFeatureRequestProductAreasPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFeatureRequestProductAreaApi),
    })
}

export const getFeatureRequestsListUrl = (projectId: string, params?: FeatureRequestsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_requests/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_requests/`
}

export const featureRequestsList = async (
    projectId: string,
    params?: FeatureRequestsListParams,
    options?: RequestInit
): Promise<PaginatedFeatureRequestListApi> => {
    return apiMutator<PaginatedFeatureRequestListApi>(getFeatureRequestsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getFeatureRequestsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/feature_requests/`
}

export const featureRequestsCreate = async (
    projectId: string,
    featureRequestCreateApi: FeatureRequestCreateApi,
    options?: RequestInit
): Promise<FeatureRequestApi> => {
    return apiMutator<FeatureRequestApi>(getFeatureRequestsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureRequestCreateApi),
    })
}

export const getFeatureRequestsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_requests/${id}/`
}

export const featureRequestsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<FeatureRequestApi> => {
    return apiMutator<FeatureRequestApi>(getFeatureRequestsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getFeatureRequestsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_requests/${id}/`
}

export const featureRequestsUpdate = async (
    projectId: string,
    id: string,
    featureRequestUpdateApi: FeatureRequestUpdateApi,
    options?: RequestInit
): Promise<FeatureRequestApi> => {
    return apiMutator<FeatureRequestApi>(getFeatureRequestsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureRequestUpdateApi),
    })
}

export const getFeatureRequestsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_requests/${id}/`
}

export const featureRequestsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedFeatureRequestUpdateApi?: PatchedFeatureRequestUpdateApi,
    options?: RequestInit
): Promise<FeatureRequestApi> => {
    return apiMutator<FeatureRequestApi>(getFeatureRequestsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFeatureRequestUpdateApi),
    })
}

export const getFeatureRequestsAddAccountCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_requests/${id}/add_account/`
}

export const featureRequestsAddAccountCreate = async (
    projectId: string,
    id: string,
    featureRequestAddAccountApi: FeatureRequestAddAccountApi,
    options?: RequestInit
): Promise<FeatureRequestApi> => {
    return apiMutator<FeatureRequestApi>(getFeatureRequestsAddAccountCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureRequestAddAccountApi),
    })
}

export const getFeatureRequestsAddEvidenceCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_requests/${id}/add_evidence/`
}

export const featureRequestsAddEvidenceCreate = async (
    projectId: string,
    id: string,
    featureRequestEvidenceCreateApi: FeatureRequestEvidenceCreateApi,
    options?: RequestInit
): Promise<FeatureRequestApi> => {
    return apiMutator<FeatureRequestApi>(getFeatureRequestsAddEvidenceCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureRequestEvidenceCreateApi),
    })
}

export const getFeatureRequestsArchiveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_requests/${id}/archive/`
}

export const featureRequestsArchiveCreate = async (
    projectId: string,
    id: string,
    featureRequestVersionApi: FeatureRequestVersionApi,
    options?: RequestInit
): Promise<FeatureRequestApi> => {
    return apiMutator<FeatureRequestApi>(getFeatureRequestsArchiveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureRequestVersionApi),
    })
}

export const getFeatureRequestsHistoryListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_requests/${id}/history/`
}

export const featureRequestsHistoryList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<FeatureRequestHistoryApi[]> => {
    return apiMutator<FeatureRequestHistoryApi[]>(getFeatureRequestsHistoryListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getFeatureRequestsRemoveEvidenceCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_requests/${id}/remove_evidence/`
}

export const featureRequestsRemoveEvidenceCreate = async (
    projectId: string,
    id: string,
    featureRequestEvidenceDeleteApi: FeatureRequestEvidenceDeleteApi,
    options?: RequestInit
): Promise<FeatureRequestApi> => {
    return apiMutator<FeatureRequestApi>(getFeatureRequestsRemoveEvidenceCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureRequestEvidenceDeleteApi),
    })
}

export const getFeatureRequestsRestoreCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_requests/${id}/restore/`
}

export const featureRequestsRestoreCreate = async (
    projectId: string,
    id: string,
    featureRequestVersionApi: FeatureRequestVersionApi,
    options?: RequestInit
): Promise<FeatureRequestApi> => {
    return apiMutator<FeatureRequestApi>(getFeatureRequestsRestoreCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureRequestVersionApi),
    })
}

export const getFeatureRequestsStatusHistoryListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_requests/${id}/status_history/`
}

export const featureRequestsStatusHistoryList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<FeatureRequestStatusHistoryApi[]> => {
    return apiMutator<FeatureRequestStatusHistoryApi[]>(getFeatureRequestsStatusHistoryListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getFeatureRequestsUpdateEvidenceCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/feature_requests/${id}/update_evidence/`
}

export const featureRequestsUpdateEvidenceCreate = async (
    projectId: string,
    id: string,
    featureRequestEvidenceUpdateApi: FeatureRequestEvidenceUpdateApi,
    options?: RequestInit
): Promise<FeatureRequestApi> => {
    return apiMutator<FeatureRequestApi>(getFeatureRequestsUpdateEvidenceCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(featureRequestEvidenceUpdateApi),
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
