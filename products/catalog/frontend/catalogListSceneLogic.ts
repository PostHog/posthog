import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { catalogNodesList, catalogRunsSyncCreate } from 'products/catalog/frontend/generated/api'
import type { CatalogNodeDTOApi } from 'products/catalog/frontend/generated/api.schemas'

import type { catalogListSceneLogicType } from './catalogListSceneLogicType'

export type CatalogKindFilter = 'all' | 'warehouse_table' | 'saved_query' | 'system_table' | 'posthog_table'
export type CatalogStatusFilter = 'all' | 'proposed' | 'approved' | 'official' | 'drift'

export const catalogListSceneLogic = kea<catalogListSceneLogicType>([
    path(['products', 'catalog', 'frontend', 'catalogListSceneLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setKindFilter: (kind: CatalogKindFilter) => ({ kind }),
        setStatusFilter: (status: CatalogStatusFilter) => ({ status }),
        setTagFilter: (tags: string[]) => ({ tags }),
        clearFilters: true,
        startSync: true,
        syncStarted: (workflowId: string) => ({ workflowId }),
        syncFailed: true,
    }),

    reducers({
        searchTerm: ['' as string, { setSearchTerm: (_, { searchTerm }) => searchTerm, clearFilters: () => '' }],
        kindFilter: [
            'all' as CatalogKindFilter,
            { setKindFilter: (_, { kind }) => kind, clearFilters: () => 'all' as CatalogKindFilter },
        ],
        statusFilter: [
            'all' as CatalogStatusFilter,
            { setStatusFilter: (_, { status }) => status, clearFilters: () => 'all' as CatalogStatusFilter },
        ],
        tagFilter: [[] as string[], { setTagFilter: (_, { tags }) => tags, clearFilters: () => [] as string[] }],
        syncing: [
            false,
            {
                startSync: () => true,
                syncStarted: () => false,
                syncFailed: () => false,
            },
        ],
    }),

    loaders(({ values }) => ({
        nodes: [
            [] as CatalogNodeDTOApi[],
            {
                loadNodes: async () => {
                    // The DRF list endpoint is paginated; walk every page so the
                    // table never silently drops rows on larger catalogs.
                    const projectId = String(values.currentProjectId)
                    const limit = 200
                    const all: CatalogNodeDTOApi[] = []
                    for (let offset = 0; ; offset += limit) {
                        const page = await catalogNodesList(projectId, { limit, offset })
                        all.push(...page.results)
                        if (!page.next || page.results.length < limit) {
                            break
                        }
                    }
                    return all
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [() => [], (): Breadcrumb[] => [{ key: 'catalog', name: 'Semantic layer' }]],
        availableTags: [
            (s) => [s.nodes],
            (nodes): string[] => {
                const set = new Set<string>()
                for (const node of nodes) {
                    for (const tag of node.tags) {
                        set.add(tag)
                    }
                }
                return Array.from(set).sort()
            },
        ],
        filteredNodes: [
            (s) => [s.nodes, s.searchTerm, s.kindFilter, s.statusFilter, s.tagFilter],
            (nodes, searchTerm, kindFilter, statusFilter, tagFilter): CatalogNodeDTOApi[] => {
                const needle = searchTerm.trim().toLowerCase()
                return nodes.filter((node) => {
                    if (kindFilter !== 'all' && node.kind !== kindFilter) {
                        return false
                    }
                    if (statusFilter !== 'all' && node.status !== statusFilter) {
                        return false
                    }
                    if (tagFilter.length > 0 && !tagFilter.some((t) => node.tags.includes(t))) {
                        return false
                    }
                    if (needle && !node.name.toLowerCase().includes(needle)) {
                        return false
                    }
                    return true
                })
            },
        ],
        hasActiveFilters: [
            (s) => [s.searchTerm, s.kindFilter, s.statusFilter, s.tagFilter],
            (searchTerm, kindFilter, statusFilter, tagFilter): boolean =>
                searchTerm.trim() !== '' || kindFilter !== 'all' || statusFilter !== 'all' || tagFilter.length > 0,
        ],
    }),

    listeners(({ actions, values }) => ({
        startSync: async () => {
            try {
                const response = await catalogRunsSyncCreate(String(values.currentProjectId))
                actions.syncStarted(response.workflow_id)
                lemonToast.success('Catalog sync started', {
                    button: { label: 'View logs', action: () => (window.location.href = urls.catalogLogs()) },
                })
            } catch (e) {
                actions.syncFailed()
                lemonToast.error(`Failed to start catalog sync: ${(e as Error).message ?? 'unknown error'}`)
            }
        },
    })),

    urlToAction(({ actions }) => ({
        '/catalog/list': () => {
            actions.loadNodes()
        },
    })),
])
