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
    source_url: string
    last_refresh_at: string | null
    last_refresh_status: '' | 'success' | 'not_modified' | 'error'
    last_refresh_error: string
}

export interface TextSourceFormValues {
    name: string
    text: string
}

export interface UrlSourceFormValues {
    name: string
    url: string
}

export type CreateTab = 'text' | 'url'

const MAX_TEXT_BYTES = 1_000_000

function apiUrl(): string {
    return `api/environments/${getCurrentTeamId()}/business_knowledge/sources`
}

function validateText({ name, text }: TextSourceFormValues): {
    name: string | undefined
    text: string | undefined
} {
    return {
        name: !name.trim() ? 'Give the source a short name' : undefined,
        text: !text.trim()
            ? 'Paste some content'
            : new Blob([text]).size > MAX_TEXT_BYTES
              ? 'Text exceeds the 1 MB cap — split it into smaller sources'
              : undefined,
    }
}

function validateUrl({ name, url }: UrlSourceFormValues): {
    name: string | undefined
    url: string | undefined
} {
    let urlError: string | undefined
    if (!url.trim()) {
        urlError = 'Paste a public HTTPS URL'
    } else {
        try {
            const parsed = new URL(url)
            if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
                urlError = 'Only http(s) URLs are allowed'
            }
        } catch {
            urlError = 'Not a valid URL'
        }
    }
    return {
        name: !name.trim() ? 'Give the source a short name' : undefined,
        url: urlError,
    }
}

export const businessKnowledgeLogic = kea<businessKnowledgeLogicType>([
    path(['products', 'business_knowledge', 'businessKnowledgeLogic']),
    actions({
        openCreateModal: true,
        closeCreateModal: true,
        setCreateTab: (tab: CreateTab) => ({ tab }),
        openEditModal: (source: KnowledgeSource) => ({ source }),
        closeEditModal: true,
        deleteSource: (id: string) => ({ id }),
        refreshSource: (id: string) => ({ id }),
    }),
    reducers({
        isCreateModalOpen: [
            false,
            {
                openCreateModal: () => true,
                closeCreateModal: () => false,
            },
        ],
        createTab: [
            'text' as CreateTab,
            {
                setCreateTab: (_, { tab }) => tab,
                closeCreateModal: () => 'text',
            },
        ],
        editingSource: [
            null as KnowledgeSource | null,
            {
                openEditModal: (_, { source }) => source,
                closeEditModal: () => null,
            },
        ],
        refreshingIds: [
            [] as string[],
            {
                refreshSource: (state, { id }) => (state.includes(id) ? state : [...state, id]),
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
                replaceSourceInList: ({ source }: { source: KnowledgeSource }) =>
                    values.sources.map((s) => (s.id === source.id ? source : s)),
            },
        ],
        editingSourceText: [
            '' as string,
            {
                loadEditingSourceText: async ({ id }: { id: string }) => {
                    const response = await api.get<{ text: string }>(`${apiUrl()}/${id}/text`)
                    return response.text ?? ''
                },
                resetEditingSourceText: () => '',
            },
        ],
    })),
    forms(({ actions, values }) => ({
        textSource: {
            defaults: { name: '', text: '' } as TextSourceFormValues,
            errors: validateText,
            submit: async ({ name, text }: TextSourceFormValues) => {
                try {
                    const created = await api.create<KnowledgeSource>(apiUrl(), {
                        name,
                        text,
                        source_type: 'text',
                    })
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
        urlSource: {
            defaults: { name: '', url: '' } as UrlSourceFormValues,
            errors: validateUrl,
            submit: async ({ name, url }: UrlSourceFormValues) => {
                try {
                    const created = await api.create<KnowledgeSource>(apiUrl(), {
                        name,
                        url,
                        source_type: 'url',
                    })
                    lemonToast.success(`"${created.name}" fetched and indexed into ${created.chunk_count} chunks`)
                    actions.closeCreateModal()
                    actions.resetUrlSource()
                    actions.loadSources()
                } catch (error: any) {
                    lemonToast.error(
                        error?.detail ||
                            error?.data?.url?.[0] ||
                            error?.data?.detail ||
                            'Could not fetch the URL. Make sure it is publicly accessible.'
                    )
                    throw error
                }
            },
        },
        editSource: {
            defaults: { name: '', text: '' } as TextSourceFormValues,
            errors: validateText,
            submit: async ({ name, text }: TextSourceFormValues) => {
                const current = values.editingSource
                if (!current) {
                    return
                }
                try {
                    const updated = await api.update<KnowledgeSource>(`${apiUrl()}/${current.id}`, { name, text })
                    lemonToast.success(`"${updated.name}" re-indexed into ${updated.chunk_count} chunks`)
                    actions.replaceSourceInList({ source: updated })
                    actions.closeEditModal()
                    actions.resetEditSource()
                    actions.resetEditingSourceText()
                } catch (error: any) {
                    lemonToast.error(
                        error?.detail ||
                            error?.data?.detail ||
                            'Could not save the changes. Check the error and try again.'
                    )
                    throw error
                }
            },
        },
    })),
    listeners(({ actions, values }) => ({
        deleteSource: async ({ id }) => {
            try {
                await api.delete(`${apiUrl()}/${id}`)
                actions.removeSourceFromList({ id })
                lemonToast.success('Knowledge source deleted')
            } catch (error: any) {
                lemonToast.error(error?.detail || 'Could not delete the source.')
            }
        },
        refreshSource: async ({ id }) => {
            try {
                const updated = await api.create<KnowledgeSource>(`${apiUrl()}/${id}/refresh`)
                actions.replaceSourceInList({ source: updated })
                if (updated.last_refresh_status === 'not_modified') {
                    lemonToast.info(`"${updated.name}" is already up to date`)
                } else {
                    lemonToast.success(`"${updated.name}" refreshed`)
                }
            } catch (error: any) {
                lemonToast.error(
                    error?.detail || error?.data?.detail || error?.data?.url?.[0] || 'Could not refresh the source.'
                )
            } finally {
                // Remove id from in-flight set by loading fresh state from server.
                actions.loadSources()
            }
        },
        openEditModal: ({ source }) => {
            actions.setEditSourceValues({ name: source.name, text: '' })
            actions.loadEditingSourceText({ id: source.id })
        },
        loadEditingSourceTextSuccess: ({ editingSourceText }) => {
            if (values.editingSource) {
                actions.setEditSourceValue('text', editingSourceText)
            }
        },
        closeEditModal: () => {
            actions.resetEditSource()
            actions.resetEditingSourceText()
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
        isEditModalOpen: [(s) => [s.editingSource], (editingSource: KnowledgeSource | null) => editingSource !== null],
    }),
    afterMount(({ actions }) => {
        actions.loadSources()
    }),
])
