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
    BusinessKnowledgeDocumentsSearchListParams,
    BusinessKnowledgeDocumentsWindowListParams,
    BusinessKnowledgeGapSuggestionsListParams,
    BusinessKnowledgeRepositoriesFileRetrieveParams,
    BusinessKnowledgeRepositoriesSearchParams,
    BusinessKnowledgeSettingsApi,
    BusinessKnowledgeSourcesDocumentsListParams,
    BusinessKnowledgeSourcesListParams,
    BusinessKnowledgeSourcesTextRetrieve200,
    CreateTextSourceApi,
    GapActionApi,
    GapTopicActionApi,
    GapTopicActionResultApi,
    KnowledgeDocumentWindowApi,
    KnowledgeGapSuggestionApi,
    KnowledgeSearchResultApi,
    KnowledgeSourceApi,
    PaginatedKnowledgeGapSuggestionListApi,
    PaginatedKnowledgeSourceDocumentListApi,
    PaginatedKnowledgeSourceListApi,
    PatchedBusinessKnowledgeSettingsUpdateApi,
    PatchedUpdateTextSourceApi,
    PlaygroundChatApi,
    PlaygroundChatListApi,
    RepositoryConnectApi,
    RepositoryConnectionApi,
    RepositoryFileApi,
    RepositorySearchResponseApi,
    RepositorySelectionApi,
    SandboxQuestionApi,
    SandboxRunApi,
    SandboxRunStartedApi,
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

export const getBusinessKnowledgeDocumentsWindowListUrl = (
    projectId: string,
    id: string,
    params: BusinessKnowledgeDocumentsWindowListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/business_knowledge/documents/${id}/window/?${stringifiedParams}`
        : `/api/projects/${projectId}/business_knowledge/documents/${id}/window/`
}

/**
 * Read-only access to parsed knowledge documents. Exposes hybrid search
 * (``search``) and a drill-down window (``window``) so an agent (PHAI or
 * MCP) can find and explore business knowledge chunks.
 */
export const businessKnowledgeDocumentsWindowList = async (
    projectId: string,
    id: string,
    params: BusinessKnowledgeDocumentsWindowListParams,
    options?: RequestInit
): Promise<KnowledgeDocumentWindowApi[]> => {
    return apiMutator<KnowledgeDocumentWindowApi[]>(getBusinessKnowledgeDocumentsWindowListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeDocumentsSearchListUrl = (
    projectId: string,
    params: BusinessKnowledgeDocumentsSearchListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/business_knowledge/documents/search/?${stringifiedParams}`
        : `/api/projects/${projectId}/business_knowledge/documents/search/`
}

/**
 * Read-only access to parsed knowledge documents. Exposes hybrid search
 * (``search``) and a drill-down window (``window``) so an agent (PHAI or
 * MCP) can find and explore business knowledge chunks.
 */
export const businessKnowledgeDocumentsSearchList = async (
    projectId: string,
    params: BusinessKnowledgeDocumentsSearchListParams,
    options?: RequestInit
): Promise<KnowledgeSearchResultApi[]> => {
    return apiMutator<KnowledgeSearchResultApi[]>(getBusinessKnowledgeDocumentsSearchListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeGapSuggestionsListUrl = (
    projectId: string,
    params?: BusinessKnowledgeGapSuggestionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/business_knowledge/gap_suggestions/?${stringifiedParams}`
        : `/api/projects/${projectId}/business_knowledge/gap_suggestions/`
}

/**
 * Surfaces topics the support AI couldn't answer from the knowledge base.
 *
 * Two list shapes controlled by the ``ticket_id`` query param:
 * - **per-ticket** (``?ticket_id=<uuid>``): individual gap rows for that ticket.
 * - **aggregated** (no ``ticket_id``): gaps grouped by normalized topic with counts,
 *   for the Business knowledge suggestions panel.
 */
export const businessKnowledgeGapSuggestionsList = async (
    projectId: string,
    params?: BusinessKnowledgeGapSuggestionsListParams,
    options?: RequestInit
): Promise<PaginatedKnowledgeGapSuggestionListApi> => {
    return apiMutator<PaginatedKnowledgeGapSuggestionListApi>(
        getBusinessKnowledgeGapSuggestionsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getBusinessKnowledgeGapSuggestionsAcceptCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/gap_suggestions/${id}/accept/`
}

/**
 * Surfaces topics the support AI couldn't answer from the knowledge base.
 *
 * Two list shapes controlled by the ``ticket_id`` query param:
 * - **per-ticket** (``?ticket_id=<uuid>``): individual gap rows for that ticket.
 * - **aggregated** (no ``ticket_id``): gaps grouped by normalized topic with counts,
 *   for the Business knowledge suggestions panel.
 */
export const businessKnowledgeGapSuggestionsAcceptCreate = async (
    projectId: string,
    id: string,
    gapActionApi?: GapActionApi,
    options?: RequestInit
): Promise<KnowledgeGapSuggestionApi> => {
    return apiMutator<KnowledgeGapSuggestionApi>(getBusinessKnowledgeGapSuggestionsAcceptCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gapActionApi),
    })
}

export const getBusinessKnowledgeGapSuggestionsDismissCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/gap_suggestions/${id}/dismiss/`
}

/**
 * Surfaces topics the support AI couldn't answer from the knowledge base.
 *
 * Two list shapes controlled by the ``ticket_id`` query param:
 * - **per-ticket** (``?ticket_id=<uuid>``): individual gap rows for that ticket.
 * - **aggregated** (no ``ticket_id``): gaps grouped by normalized topic with counts,
 *   for the Business knowledge suggestions panel.
 */
export const businessKnowledgeGapSuggestionsDismissCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<KnowledgeGapSuggestionApi> => {
    return apiMutator<KnowledgeGapSuggestionApi>(getBusinessKnowledgeGapSuggestionsDismissCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getBusinessKnowledgeGapSuggestionsAcceptTopicCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/gap_suggestions/accept_topic/`
}

/**
 * Accept all pending suggestions for a normalized topic cluster.
 */
export const businessKnowledgeGapSuggestionsAcceptTopicCreate = async (
    projectId: string,
    gapTopicActionApi: GapTopicActionApi,
    options?: RequestInit
): Promise<GapTopicActionResultApi> => {
    return apiMutator<GapTopicActionResultApi>(getBusinessKnowledgeGapSuggestionsAcceptTopicCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gapTopicActionApi),
    })
}

export const getBusinessKnowledgeGapSuggestionsDismissTopicCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/gap_suggestions/dismiss_topic/`
}

/**
 * Dismiss all pending suggestions for a normalized topic cluster.
 */
export const businessKnowledgeGapSuggestionsDismissTopicCreate = async (
    projectId: string,
    gapTopicActionApi: GapTopicActionApi,
    options?: RequestInit
): Promise<GapTopicActionResultApi> => {
    return apiMutator<GapTopicActionResultApi>(getBusinessKnowledgeGapSuggestionsDismissTopicCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gapTopicActionApi),
    })
}

export const getBusinessKnowledgePlaygroundChatsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/playground/chats/`
}

/**
 * Chats started by the current user in this project.
 * @summary List business knowledge playground chats
 */
export const businessKnowledgePlaygroundChatsList = async (
    projectId: string,
    options?: RequestInit
): Promise<PlaygroundChatListApi[]> => {
    return apiMutator<PlaygroundChatListApi[]>(getBusinessKnowledgePlaygroundChatsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgePlaygroundChatsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/playground/chats/`
}

/**
 * Create an empty chat. The first question sets the title.
 * @summary Create a business knowledge playground chat
 */
export const businessKnowledgePlaygroundChatsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<PlaygroundChatApi> => {
    return apiMutator<PlaygroundChatApi>(getBusinessKnowledgePlaygroundChatsCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getBusinessKnowledgePlaygroundChatsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/playground/chats/${id}/`
}

/**
 * Reload a chat and its turns. Each turn's answer comes from its sandbox run. A chat started before AI data processing was turned off can still be read.
 * @summary Get a business knowledge playground chat
 */
export const businessKnowledgePlaygroundChatsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PlaygroundChatApi> => {
    return apiMutator<PlaygroundChatApi>(getBusinessKnowledgePlaygroundChatsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgePlaygroundChatsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/playground/chats/${id}/`
}

/**
 * Deletes the chat and its turns. Does not cancel a running sandbox agent.
 * @summary Delete a business knowledge playground chat
 */
export const businessKnowledgePlaygroundChatsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBusinessKnowledgePlaygroundChatsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getBusinessKnowledgePlaygroundChatsAskCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/playground/chats/${id}/ask/`
}

/**
 * Append a turn and start a sandbox run. A second question in the same chat while its answer is still open returns 409. Other chats can run at the same time, up to 3 open answers per person.
 * @summary Ask a question in a playground chat
 */
export const businessKnowledgePlaygroundChatsAskCreate = async (
    projectId: string,
    id: string,
    sandboxQuestionApi: SandboxQuestionApi,
    options?: RequestInit
): Promise<PlaygroundChatApi> => {
    return apiMutator<PlaygroundChatApi>(getBusinessKnowledgePlaygroundChatsAskCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sandboxQuestionApi),
    })
}

export const getBusinessKnowledgeRepositoriesConnectCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/repositories/connect/`
}

/**
 * Stores the installation for this environment. Switching installations clears the selected repositories.
 * @summary Connect a GitHub installation to business knowledge
 */
export const businessKnowledgeRepositoriesConnectCreate = async (
    projectId: string,
    repositoryConnectApi: RepositoryConnectApi,
    options?: RequestInit
): Promise<RepositoryConnectionApi> => {
    return apiMutator<RepositoryConnectionApi>(getBusinessKnowledgeRepositoriesConnectCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(repositoryConnectApi),
    })
}

export const getBusinessKnowledgeRepositoriesDisconnectCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/repositories/disconnect/`
}

/**
 * Clears the installation and the selected repositories for this environment.
 * @summary Disconnect GitHub from business knowledge
 */
export const businessKnowledgeRepositoriesDisconnectCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<RepositoryConnectionApi> => {
    return apiMutator<RepositoryConnectionApi>(getBusinessKnowledgeRepositoriesDisconnectCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getBusinessKnowledgeRepositoriesFileRetrieveUrl = (
    projectId: string,
    params: BusinessKnowledgeRepositoriesFileRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/business_knowledge/repositories/file/?${stringifiedParams}`
        : `/api/projects/${projectId}/business_knowledge/repositories/file/`
}

/**
 * Reads one file whose path is in the cached file list, at the cached commit. The path must come from the repository search.
 * @summary Read a file from a selected GitHub repository
 */
export const businessKnowledgeRepositoriesFileRetrieve = async (
    projectId: string,
    params: BusinessKnowledgeRepositoriesFileRetrieveParams,
    options?: RequestInit
): Promise<RepositoryFileApi> => {
    return apiMutator<RepositoryFileApi>(getBusinessKnowledgeRepositoriesFileRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeRepositoriesSearchUrl = (
    projectId: string,
    params: BusinessKnowledgeRepositoriesSearchParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/business_knowledge/repositories/search/?${stringifiedParams}`
        : `/api/projects/${projectId}/business_knowledge/repositories/search/`
}

/**
 * Matches file paths and README text in the cached default-branch file list. Pass file names or identifiers, then read a file. Does not search file contents.
 * @summary Search selected GitHub repositories
 */
export const businessKnowledgeRepositoriesSearch = async (
    projectId: string,
    params: BusinessKnowledgeRepositoriesSearchParams,
    options?: RequestInit
): Promise<RepositorySearchResponseApi> => {
    return apiMutator<RepositorySearchResponseApi>(getBusinessKnowledgeRepositoriesSearchUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeRepositoriesSelectionCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/repositories/selection/`
}

/**
 * Every name must be a repository the connected installation can see. Names are stored lowercased.
 * @summary Replace the repositories business knowledge can read
 */
export const businessKnowledgeRepositoriesSelectionCreate = async (
    projectId: string,
    repositorySelectionApi: RepositorySelectionApi,
    options?: RequestInit
): Promise<RepositoryConnectionApi> => {
    return apiMutator<RepositoryConnectionApi>(getBusinessKnowledgeRepositoriesSelectionCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(repositorySelectionApi),
    })
}

export const getBusinessKnowledgeRepositoriesStatusRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/repositories/status/`
}

/**
 * The GitHub installation and the repositories this environment allows business knowledge to read.
 * @summary Get the GitHub repositories connected to business knowledge
 */
export const businessKnowledgeRepositoriesStatusRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<RepositoryConnectionApi> => {
    return apiMutator<RepositoryConnectionApi>(getBusinessKnowledgeRepositoriesStatusRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeSandboxCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/sandbox/`
}

/**
 * Start a sandbox agent that can search only this project's business knowledge. Returns immediately.
 * @summary Ask a business knowledge sandbox question
 */
export const businessKnowledgeSandboxCreate = async (
    projectId: string,
    sandboxQuestionApi: SandboxQuestionApi,
    options?: RequestInit
): Promise<SandboxRunStartedApi> => {
    return apiMutator<SandboxRunStartedApi>(getBusinessKnowledgeSandboxCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sandboxQuestionApi),
    })
}

export const getBusinessKnowledgeSandboxRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/sandbox/${id}/`
}

/**
 * Poll a sandbox run started by the current user. A run that started before AI data processing was turned off can still be read.
 * @summary Get a business knowledge sandbox run
 */
export const businessKnowledgeSandboxRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SandboxRunApi> => {
    return apiMutator<SandboxRunApi>(getBusinessKnowledgeSandboxRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeSettingsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/settings/`
}

/**
 * Fetch whether this project learns from resolved support tickets, and whether Support is on in this environment.
 * @summary Get business knowledge settings
 */
export const businessKnowledgeSettingsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<BusinessKnowledgeSettingsApi> => {
    return apiMutator<BusinessKnowledgeSettingsApi>(getBusinessKnowledgeSettingsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeSettingsPartialUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/settings/`
}

/**
 * Partially update Business knowledge learning settings. Enabling learn-from-support requires Support to be on in this environment.
 * @summary Update business knowledge settings
 */
export const businessKnowledgeSettingsPartialUpdate = async (
    projectId: string,
    patchedBusinessKnowledgeSettingsUpdateApi?: PatchedBusinessKnowledgeSettingsUpdateApi,
    options?: RequestInit
): Promise<BusinessKnowledgeSettingsApi> => {
    return apiMutator<BusinessKnowledgeSettingsApi>(getBusinessKnowledgeSettingsPartialUpdateUrl(projectId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedBusinessKnowledgeSettingsUpdateApi),
    })
}

export const getBusinessKnowledgeSourcesListUrl = (projectId: string, params?: BusinessKnowledgeSourcesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/business_knowledge/sources/?${stringifiedParams}`
        : `/api/projects/${projectId}/business_knowledge/sources/`
}

export const businessKnowledgeSourcesList = async (
    projectId: string,
    params?: BusinessKnowledgeSourcesListParams,
    options?: RequestInit
): Promise<PaginatedKnowledgeSourceListApi> => {
    return apiMutator<PaginatedKnowledgeSourceListApi>(getBusinessKnowledgeSourcesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeSourcesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/business_knowledge/sources/`
}

export const businessKnowledgeSourcesCreate = async (
    projectId: string,
    createTextSourceApi: CreateTextSourceApi,
    options?: RequestInit
): Promise<KnowledgeSourceApi> => {
    return apiMutator<KnowledgeSourceApi>(getBusinessKnowledgeSourcesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createTextSourceApi),
    })
}

export const getBusinessKnowledgeSourcesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/sources/${id}/`
}

export const businessKnowledgeSourcesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<KnowledgeSourceApi> => {
    return apiMutator<KnowledgeSourceApi>(getBusinessKnowledgeSourcesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBusinessKnowledgeSourcesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/sources/${id}/`
}

export const businessKnowledgeSourcesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateTextSourceApi?: PatchedUpdateTextSourceApi,
    options?: RequestInit
): Promise<KnowledgeSourceApi> => {
    return apiMutator<KnowledgeSourceApi>(getBusinessKnowledgeSourcesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateTextSourceApi),
    })
}

export const getBusinessKnowledgeSourcesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/sources/${id}/`
}

export const businessKnowledgeSourcesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getBusinessKnowledgeSourcesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getBusinessKnowledgeSourcesDocumentsListUrl = (
    projectId: string,
    id: string,
    params?: BusinessKnowledgeSourcesDocumentsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/business_knowledge/sources/${id}/documents/?${stringifiedParams}`
        : `/api/projects/${projectId}/business_knowledge/sources/${id}/documents/`
}

export const businessKnowledgeSourcesDocumentsList = async (
    projectId: string,
    id: string,
    params?: BusinessKnowledgeSourcesDocumentsListParams,
    options?: RequestInit
): Promise<PaginatedKnowledgeSourceDocumentListApi> => {
    return apiMutator<PaginatedKnowledgeSourceDocumentListApi>(
        getBusinessKnowledgeSourcesDocumentsListUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getBusinessKnowledgeSourcesRefreshCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/sources/${id}/refresh/`
}

export const businessKnowledgeSourcesRefreshCreate = async (
    projectId: string,
    id: string,
    knowledgeSourceApi?: NonReadonly<KnowledgeSourceApi>,
    options?: RequestInit
): Promise<KnowledgeSourceApi> => {
    return apiMutator<KnowledgeSourceApi>(getBusinessKnowledgeSourcesRefreshCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(knowledgeSourceApi),
    })
}

export const getBusinessKnowledgeSourcesTextRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/business_knowledge/sources/${id}/text/`
}

export const businessKnowledgeSourcesTextRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<BusinessKnowledgeSourcesTextRetrieve200> => {
    return apiMutator<BusinessKnowledgeSourcesTextRetrieve200>(
        getBusinessKnowledgeSourcesTextRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}
