import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { KnowledgeSource } from './scenes/businessKnowledgeLogic'

function apiUrl(): string {
    return `api/environments/${getCurrentTeamId()}/business_knowledge/sources`
}

export async function listSources(): Promise<KnowledgeSource[]> {
    const response = await api.get(apiUrl())
    return (response.results ?? response ?? []) as KnowledgeSource[]
}

export async function getSourceText(id: string): Promise<{ id: string; text: string }> {
    const response = await api.get<{ text: string }>(`${apiUrl()}/${id}/text`)
    return { id, text: response.text ?? '' }
}

export async function createTextSource(name: string, text: string): Promise<KnowledgeSource> {
    return await api.create<KnowledgeSource>(apiUrl(), { name, text, source_type: 'text' })
}

export async function createUrlSource(payload: Record<string, unknown>): Promise<KnowledgeSource> {
    return await api.create<KnowledgeSource>(apiUrl(), payload)
}

export async function createFileSource(formData: FormData): Promise<KnowledgeSource> {
    return await api.create<KnowledgeSource>(apiUrl(), formData)
}

export async function updateSource(id: string, payload: Record<string, unknown>): Promise<KnowledgeSource> {
    return await api.update<KnowledgeSource>(`${apiUrl()}/${id}`, payload)
}

export async function deleteSource(id: string): Promise<void> {
    await api.delete(`${apiUrl()}/${id}`)
}

export async function refreshSource(id: string): Promise<KnowledgeSource> {
    return await api.create<KnowledgeSource>(`${apiUrl()}/${id}/refresh`)
}
