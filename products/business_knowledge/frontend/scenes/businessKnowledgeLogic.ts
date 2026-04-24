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
export type CrawlMode = 'single' | 'sitemap' | 'same_origin' | 'github_repo'

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
    crawl_mode: '' | CrawlMode
    crawl_config: {
        include_globs?: string[]
        exclude_globs?: string[]
        max_pages?: number
        max_depth?: number
    }
}

export interface TextSourceFormValues {
    name: string
    text: string
}

export interface UrlSourceFormValues {
    name: string
    url: string
    crawl_mode: CrawlMode
    // Comma/newline-separated globs — split server-side. Keeping the form
    // state as a plain string is much easier than a list-of-inputs widget.
    include_globs: string
    exclude_globs: string
    max_pages: number
    max_depth: number
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

function validateUrl({ name, url, max_pages }: UrlSourceFormValues): {
    name: string | undefined
    url: string | undefined
    max_pages: string | undefined
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
        max_pages: max_pages < 1 || max_pages > 500 ? 'max_pages must be between 1 and 500' : undefined,
    }
}

function splitGlobs(raw: string): string[] {
    return raw
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean)
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
        refreshSourceDone: (id: string) => ({ id }),
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
                refreshSourceDone: (state, { id }) => state.filter((x) => x !== id),
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
            defaults: {
                name: '',
                url: '',
                crawl_mode: 'single',
                include_globs: '',
                exclude_globs: '',
                max_pages: 50,
                max_depth: 2,
            } as UrlSourceFormValues,
            errors: validateUrl,
            submit: async (values: UrlSourceFormValues) => {
                const payload: Record<string, unknown> = {
                    name: values.name,
                    url: values.url,
                    source_type: 'url',
                    crawl_mode: values.crawl_mode,
                }
                if (values.crawl_mode !== 'single') {
                    payload.include_globs = splitGlobs(values.include_globs)
                    payload.exclude_globs = splitGlobs(values.exclude_globs)
                    payload.max_pages = values.max_pages
                    payload.max_depth = values.max_depth
                }
                try {
                    const created = await api.create<KnowledgeSource>(apiUrl(), payload)
                    const pageLabel =
                        created.crawl_mode && created.crawl_mode !== 'single'
                            ? ` (${created.document_count} pages)`
                            : ''
                    lemonToast.success(`"${created.name}" indexed into ${created.chunk_count} chunks${pageLabel}`)
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
                actions.refreshSourceDone(id)
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
