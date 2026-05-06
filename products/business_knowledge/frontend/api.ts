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
import type { KnowledgeSourceDTOApi } from './generated/api.schemas'

export type { KnowledgeSourceDTOApi }

export async function listSources(): Promise<KnowledgeSourceDTOApi[]> {
    const response = await businessKnowledgeSourcesList(String(getCurrentTeamId()))
    return response.results
}

export async function getSourceText(id: string): Promise<{ id: string; text: string }> {
    const response = await businessKnowledgeSourcesTextRetrieve(String(getCurrentTeamId()), id)
    return { id, text: response.text ?? '' }
}

export async function createTextSource(name: string, text: string): Promise<KnowledgeSourceDTOApi> {
    return await businessKnowledgeSourcesCreate(String(getCurrentTeamId()), { name, text })
}

export async function createUrlSource(payload: Record<string, unknown>): Promise<KnowledgeSourceDTOApi> {
    return await businessKnowledgeSourcesCreate(String(getCurrentTeamId()), payload as any)
}

export async function createFileSource(formData: FormData): Promise<KnowledgeSourceDTOApi> {
    return await apiMutator<KnowledgeSourceDTOApi>(
        `/api/environments/${getCurrentTeamId()}/business_knowledge/sources/`,
        { method: 'POST', body: formData }
    )
}

export async function updateSource(id: string, payload: Record<string, unknown>): Promise<KnowledgeSourceDTOApi> {
    return await businessKnowledgeSourcesPartialUpdate(String(getCurrentTeamId()), id, payload as any)
}

export async function deleteSource(id: string): Promise<void> {
    await businessKnowledgeSourcesDestroy(String(getCurrentTeamId()), id)
}

export async function refreshSource(id: string): Promise<KnowledgeSourceDTOApi> {
    return await businessKnowledgeSourcesRefreshCreate(String(getCurrentTeamId()), id, {} as any)
}
