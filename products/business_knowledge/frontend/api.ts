import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { apiMutator } from '../../../frontend/src/lib/api-orval-mutator'
import {
    businessKnowledgeSourcesCreate,
    businessKnowledgeSourcesDestroy,
    businessKnowledgeSourcesList,
    businessKnowledgeSourcesPartialUpdate,
    businessKnowledgeSourcesRefreshCreate,
    businessKnowledgeSourcesTextRetrieve,
} from './generated/api'
import type { CrawlModeEnumApi, KnowledgeSourceApi } from './generated/api.schemas'

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

export async function listSources(): Promise<KnowledgeSourceApi[]> {
    const response = await businessKnowledgeSourcesList(String(getCurrentTeamId()), { limit: 1000 })
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
