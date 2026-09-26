import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { apiMutator } from '../../../frontend/src/lib/api-orval-mutator'
import {
    businessKnowledgeSourcesCreate,
    businessKnowledgeSourcesDestroy,
    businessKnowledgeSourcesDocumentsList,
    businessKnowledgeSourcesList,
    businessKnowledgeSourcesPartialUpdate,
    businessKnowledgeSourcesRefreshCreate,
    businessKnowledgeSourcesRetrieve,
    businessKnowledgeSourcesTextRetrieve,
} from './generated/api'
import type {
    BusinessKnowledgeSourcesListAddedBy,
    BusinessKnowledgeSourcesListParams,
    BusinessKnowledgeSourcesListSourceType,
    CrawlModeEnumApi,
    KnowledgeSourceApi,
    KnowledgeSourceDocumentApi,
} from './generated/api.schemas'

export type { KnowledgeSourceApi as KnowledgeSourceDTOApi }

// TODO: replace with generated types once the backend exposes URL source serializers
export type RefreshIntervalValue = 'manual' | '1h' | '6h' | '24h' | '7d'
export type RefreshIntervalOption = { value: RefreshIntervalValue; label: string }

export interface CreateUrlSourcePayload {
    name: string
    url: string
    source_type: 'url'
    crawl_mode: CrawlModeEnumApi
    include_globs?: string[]
    exclude_globs?: string[]
    max_pages?: number
    max_depth?: number
    refresh_interval?: RefreshIntervalValue
    always_include?: boolean
}

export interface UpdateSourcePayload {
    name?: string
    text?: string
    url?: string
    crawl_mode?: CrawlModeEnumApi
    include_globs?: string[]
    exclude_globs?: string[]
    max_pages?: number
    max_depth?: number
    refresh_interval?: RefreshIntervalValue
    always_include?: boolean
}

export async function listSources(params?: {
    search?: string
    sourceType?: string
    addedBy?: string
}): Promise<KnowledgeSourceApi[]> {
    const search = params?.search?.trim()
    const sourceType =
        params?.sourceType && params.sourceType !== 'all'
            ? (params.sourceType as BusinessKnowledgeSourcesListSourceType)
            : undefined
    const addedBy =
        params?.addedBy && params.addedBy !== 'all'
            ? (params.addedBy as BusinessKnowledgeSourcesListAddedBy)
            : undefined
    const query: BusinessKnowledgeSourcesListParams = {
        limit: 1000,
        ...(search ? { search } : {}),
        ...(sourceType ? { source_type: sourceType } : {}),
        ...(addedBy ? { added_by: addedBy } : {}),
    }
    const response = await businessKnowledgeSourcesList(String(getCurrentTeamId()), query)
    return response.results
}

export async function getSource(id: string): Promise<KnowledgeSourceApi> {
    return await businessKnowledgeSourcesRetrieve(String(getCurrentTeamId()), id)
}

export async function getSourceDocuments(id: string): Promise<KnowledgeSourceDocumentApi[]> {
    // 500 matches the crawl cap (MAX_URLS_PER_SOURCE), so one page is the full set.
    const response = await businessKnowledgeSourcesDocumentsList(String(getCurrentTeamId()), id, { limit: 500 })
    return response.results
}

export async function getSourceText(id: string): Promise<{ id: string; text: string }> {
    const response = await businessKnowledgeSourcesTextRetrieve(String(getCurrentTeamId()), id)
    return { id, text: response.text ?? '' }
}

export async function createTextSource(
    name: string,
    text: string,
    always_include: boolean = false
): Promise<KnowledgeSourceApi> {
    return await businessKnowledgeSourcesCreate(String(getCurrentTeamId()), { name, text, always_include })
}

export async function createUrlSource(payload: CreateUrlSourcePayload): Promise<KnowledgeSourceApi> {
    return await businessKnowledgeSourcesCreate(
        String(getCurrentTeamId()),
        payload as unknown as Parameters<typeof businessKnowledgeSourcesCreate>[1]
    )
}

export async function createFileSource(formData: FormData): Promise<KnowledgeSourceApi> {
    return await apiMutator<KnowledgeSourceApi>(`/api/projects/${getCurrentTeamId()}/business_knowledge/sources/`, {
        method: 'POST',
        body: formData,
    })
}

export async function updateSource(id: string, payload: UpdateSourcePayload): Promise<KnowledgeSourceApi> {
    return await businessKnowledgeSourcesPartialUpdate(
        String(getCurrentTeamId()),
        id,
        payload as Parameters<typeof businessKnowledgeSourcesPartialUpdate>[2]
    )
}

export async function deleteSource(id: string): Promise<void> {
    await businessKnowledgeSourcesDestroy(String(getCurrentTeamId()), id)
}

export async function refreshSource(id: string): Promise<KnowledgeSourceApi> {
    return await businessKnowledgeSourcesRefreshCreate(String(getCurrentTeamId()), id)
}
