import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import {
    createFileSource,
    createTextSource,
    createUrlSource,
    deleteSource,
    getSourceText,
    listSources,
    refreshSource,
    updateSource,
} from '../api'
import type { CreateUrlSourcePayload, RefreshIntervalValue, UpdateSourcePayload } from '../api'
import type { KnowledgeSourceApi } from '../generated/api.schemas'
import type { businessKnowledgeLogicType } from './businessKnowledgeLogicType'

export type KnowledgeSource = KnowledgeSourceApi
export type CrawlMode = 'single' | 'sitemap' | 'same_origin' | 'github_repo'

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
    // Background auto-refresh cadence, sent on both create and edit.
    refresh_interval: RefreshIntervalValue
}

export interface FileSourceFormValues {
    name: string
    file: File | null
}

export type CreateTab = 'text' | 'url' | 'file'

const MAX_TEXT_BYTES = 1_000_000

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
                    return await listSources()
                },
                removeSourceFromList: ({ id }: { id: string }) => values.sources.filter((s) => s.id !== id),
                replaceSourceInList: ({ source }: { source: KnowledgeSource }) =>
                    values.sources.map((s) => (s.id === source.id ? source : s)),
            },
        ],
        editingSourceText: [
            { id: '', text: '' } as { id: string; text: string },
            {
                loadEditingSourceText: async ({ id }: { id: string }) => {
                    return await getSourceText(id)
                },
                resetEditingSourceText: () => ({ id: '', text: '' }),
            },
        ],
    })),
    forms(({ actions, values }) => ({
        textSource: {
            defaults: { name: '', text: '' } as TextSourceFormValues,
            errors: validateText,
            submit: async ({ name, text }: TextSourceFormValues) => {
                try {
                    const created = await createTextSource(name, text)
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
                refresh_interval: 'manual',
            } as UrlSourceFormValues,
            errors: validateUrl,
            submit: async (values: UrlSourceFormValues) => {
                const includeGlobs = splitGlobs(values.include_globs)
                const payload: CreateUrlSourcePayload = {
                    name: values.name,
                    url: values.url,
                    source_type: 'url',
                    crawl_mode: values.crawl_mode,
                    refresh_interval: values.refresh_interval,
                    ...(values.crawl_mode !== 'single' && {
                        // Only send include_globs when the user explicitly set them;
                        // otherwise the backend auto-derives scope from the entry URL path.
                        ...(includeGlobs.length > 0 && { include_globs: includeGlobs }),
                        exclude_globs: splitGlobs(values.exclude_globs),
                        max_pages: values.max_pages,
                        max_depth: values.max_depth,
                    }),
                }
                try {
                    const created = await createUrlSource(payload)
                    // Ingestion runs in the background; the source starts PROCESSING
                    // and the list polls until it flips to ready.
                    lemonToast.success(`"${created.name}" added — fetching and indexing in the background`)
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
        fileSource: {
            defaults: { name: '', file: null } as FileSourceFormValues,
            errors: ({ name, file }: FileSourceFormValues) => ({
                name: !name.trim() ? 'Give the source a short name' : undefined,
                file: !file
                    ? 'Select a file to upload'
                    : file.size > 50 * 1024 * 1024
                      ? 'File exceeds the 50 MB cap'
                      : undefined,
            }),
            submit: async ({ name, file }: FileSourceFormValues) => {
                if (!file) {
                    return
                }
                const formData = new FormData()
                formData.append('name', name)
                formData.append('file', file)
                formData.append('source_type', 'file')
                try {
                    const created = await createFileSource(formData)
                    lemonToast.success(`"${created.name}" indexed into ${created.chunk_count} chunks`)
                    actions.closeCreateModal()
                    actions.resetFileSource()
                    actions.loadSources()
                } catch (error: any) {
                    lemonToast.error(
                        error?.detail ||
                            error?.data?.file?.[0] ||
                            error?.data?.detail ||
                            'Could not parse the file. Check format and try again.'
                    )
                    throw error
                }
            },
        },
        editSource: {
            defaults: { name: '', text: '' } as TextSourceFormValues,
            errors: ({ name, text }: TextSourceFormValues) => {
                const isText = values.editingSource?.source_type === 'text'
                return {
                    name: !name.trim() ? 'Give the source a short name' : undefined,
                    text: isText
                        ? !text.trim()
                            ? 'Paste some content'
                            : new Blob([text]).size > MAX_TEXT_BYTES
                              ? 'Text exceeds the 1 MB cap — split it into smaller sources'
                              : undefined
                        : undefined,
                }
            },
            submit: async ({ name, text }: TextSourceFormValues) => {
                const current = values.editingSource
                if (!current) {
                    return
                }
                const isText = current.source_type === 'text'
                const payload: UpdateSourcePayload = { name, ...(isText && { text }) }
                try {
                    const updated = await updateSource(current.id, payload)
                    const msg = isText
                        ? `"${updated.name}" re-indexed into ${updated.chunk_count} chunks`
                        : `"${updated.name}" renamed`
                    lemonToast.success(msg)
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
        editUrlSource: {
            defaults: {
                name: '',
                url: '',
                crawl_mode: 'single' as CrawlMode,
                include_globs: '',
                exclude_globs: '',
                max_pages: 50,
                max_depth: 2,
                refresh_interval: 'manual',
            } as UrlSourceFormValues,
            errors: validateUrl,
            submit: async (vals: UrlSourceFormValues) => {
                const current = values.editingSource
                if (!current) {
                    return
                }
                const editIncludeGlobs = splitGlobs(vals.include_globs)
                const payload: UpdateSourcePayload = {
                    name: vals.name,
                    url: vals.url,
                    crawl_mode: vals.crawl_mode,
                    refresh_interval: vals.refresh_interval,
                    ...(vals.crawl_mode !== 'single' && {
                        ...(editIncludeGlobs.length > 0 && { include_globs: editIncludeGlobs }),
                        exclude_globs: splitGlobs(vals.exclude_globs),
                        max_pages: vals.max_pages,
                        max_depth: vals.max_depth,
                    }),
                }
                try {
                    const updated = await updateSource(current.id, payload)
                    lemonToast.success(`"${updated.name}" updated`)
                    actions.replaceSourceInList({ source: updated })
                    actions.closeEditModal()
                    actions.resetEditUrlSource()
                } catch (error: any) {
                    lemonToast.error(
                        error?.detail ||
                            error?.data?.url?.[0] ||
                            error?.data?.detail ||
                            'Could not save the changes. Check the error and try again.'
                    )
                    throw error
                }
            },
        },
    })),
    listeners(({ actions, values, cache }) => ({
        loadSourcesSuccess: ({ sources }) => {
            // URL ingestion runs in the background — poll while anything is still
            // processing so the row flips to ready (or error) without a manual reload.
            // After that, embeddings are generated by an hourly background job, so
            // keep polling at a much slower cadence until everything is fully indexed.
            const isProcessing = sources.some((s) => s.status === 'processing')
            const isEmbedding = sources.some((s) => s.status === 'ready' && s.embedding_status === 'pending')
            if (isProcessing || isEmbedding) {
                cache.disposables.add(() => {
                    const id = setTimeout(() => actions.loadSources(), isProcessing ? 3000 : 60000)
                    return () => clearTimeout(id)
                }, 'pollProcessing')
            } else {
                cache.disposables.dispose('pollProcessing')
            }
        },
        deleteSource: async ({ id }) => {
            try {
                await deleteSource(id)
                actions.removeSourceFromList({ id })
                lemonToast.success('Knowledge source deleted')
            } catch (error: any) {
                lemonToast.error(error?.detail || 'Could not delete the source.')
            }
        },
        refreshSource: async ({ id }) => {
            try {
                const updated = await refreshSource(id)
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
            if (source.source_type === 'url') {
                const cfg = (source.crawl_config || {}) as {
                    include_globs?: string[]
                    exclude_globs?: string[]
                    max_pages?: number
                    max_depth?: number
                }
                actions.setEditUrlSourceValues({
                    name: source.name,
                    url: source.source_url,
                    crawl_mode: (source.crawl_mode || 'single') as CrawlMode,
                    include_globs: (cfg.include_globs || []).join('\n'),
                    exclude_globs: (cfg.exclude_globs || []).join('\n'),
                    max_pages: cfg.max_pages ?? 50,
                    max_depth: cfg.max_depth ?? 2,
                    refresh_interval: (source.refresh_interval || 'manual') as RefreshIntervalValue,
                })
            } else {
                actions.setEditSourceValues({ name: source.name, text: '' })
                if (source.source_type === 'text') {
                    actions.loadEditingSourceText({ id: source.id })
                }
            }
        },
        loadEditingSourceTextSuccess: ({ editingSourceText }) => {
            if (values.editingSource && values.editingSource.id === editingSourceText.id) {
                actions.setEditSourceValue('text', editingSourceText.text)
            }
        },
        closeEditModal: () => {
            actions.resetEditSource()
            actions.resetEditUrlSource()
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
