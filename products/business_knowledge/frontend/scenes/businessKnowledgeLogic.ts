import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { businessKnowledgeLogicType } from './businessKnowledgeLogicType'

// Mirror of products.business_knowledge.backend.facade.contracts.KnowledgeSourceDTO.
// Hand-typed for now; once the OpenAPI types include this endpoint, swap to
// the generated interface.
export interface KnowledgeSource {
    id: string
    team_id: number
    name: string
    source_type: 'text' | 'url' | 'file'
    status: 'pending' | 'processing' | 'ready' | 'error'
    error_message: string
    document_count: number
    chunk_count: number
    created_at: string
    updated_at: string | null
}

export interface CreateTextFormValues {
    name: string
    text: string
}

const MAX_TEXT_BYTES = 1_000_000

function apiUrl(): string {
    return `api/environments/${getCurrentTeamId()}/business_knowledge/sources`
}

export const businessKnowledgeLogic = kea<businessKnowledgeLogicType>([
    path(['products', 'business_knowledge', 'businessKnowledgeLogic']),
    actions({
        openCreateModal: true,
        closeCreateModal: true,
        deleteSource: (id: string) => ({ id }),
    }),
    reducers({
        isCreateModalOpen: [
            false,
            {
                openCreateModal: () => true,
                closeCreateModal: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
        sources: [
            [] as KnowledgeSource[],
            {
                loadSources: async () => {
                    const response = await api.get(apiUrl())
                    return (response.results ?? response ?? []) as KnowledgeSource[]
                },
                removeSourceFromList: ({ id }: { id: string }) => values.sources.filter((s) => s.id !== id),
            },
        ],
    })),
    forms(({ actions }) => ({
        textSource: {
            defaults: { name: '', text: '' } as CreateTextFormValues,
            errors: ({ name, text }: CreateTextFormValues) => ({
                name: !name.trim() ? 'Give the source a short name' : undefined,
                text: !text.trim()
                    ? 'Paste some content'
                    : new Blob([text]).size > MAX_TEXT_BYTES
                      ? 'Text exceeds the 1 MB cap — split it into smaller sources'
                      : undefined,
            }),
            submit: async ({ name, text }: CreateTextFormValues) => {
                try {
                    const created = await api.create<KnowledgeSource>(apiUrl(), { name, text })
                    lemonToast.success(`"${created.name}" indexed into ${created.chunk_count} chunks`)
                    actions.closeCreateModal()
                    actions.resetTextSource()
                    actions.loadSources()
                } catch (error: any) {
                    lemonToast.error(
                        error?.detail ||
                            error?.data?.detail ||
                            'Could not save the source. Check the error and try again.'
                    )
                    throw error
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        deleteSource: async ({ id }) => {
            try {
                await api.delete(`${apiUrl()}/${id}`)
                actions.removeSourceFromList({ id })
                lemonToast.success('Knowledge source deleted')
            } catch (error: any) {
                lemonToast.error(error?.detail || 'Could not delete the source.')
            }
        },
    })),
    selectors({
        readyCount: [
            (s) => [s.sources],
            (sources: KnowledgeSource[]) => sources.filter((s) => s.status === 'ready').length,
        ],
        totalChunks: [
            (s) => [s.sources],
            (sources: KnowledgeSource[]) => sources.reduce((sum, s) => sum + (s.chunk_count || 0), 0),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSources()
    }),
])
