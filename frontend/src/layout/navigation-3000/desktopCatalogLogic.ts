import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { fileSystemTypes, getTreeItemsMetadata, getTreeItemsProducts } from '~/products'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'

import { classicEmbedContext, isClassicEmbedPath } from './classicEmbedContext'

export const LIBRARY_PAGE_SIZE = 50
const TOOL_TYPES = new Set(['endpoints', 'live_debugger', 'task'])

export function desktopObjectHref(entry: Pick<FileSystemEntry, 'href' | 'type' | 'ref'>): string | undefined {
    const baseType = entry.type?.split('/')[0] ?? ''
    const definition = Object.hasOwn(fileSystemTypes, baseType)
        ? fileSystemTypes[baseType as keyof typeof fileSystemTypes]
        : undefined
    const href = entry.href || (entry.ref && definition?.href(entry.ref))
    if (!href || !classicEmbedContext) {
        return undefined
    }
    let target: URL
    try {
        target = new URL(href, window.location.origin)
    } catch {
        return undefined
    }
    const projectPath = target.pathname.startsWith('/project/')
        ? target.pathname
        : `/project/${classicEmbedContext.projectId}${target.pathname}`
    if (
        target.origin !== window.location.origin ||
        target.username ||
        target.password ||
        /^\/(?:organization|organizations|settings|login|logout|admin|api)(?:\/|$)/.test(target.pathname) ||
        !isClassicEmbedPath(projectPath, classicEmbedContext.projectId)
    ) {
        return undefined
    }
    return `${projectPath}${target.search}${target.hash}`
}

export interface desktopCatalogLogicValues {
    searchParams: Record<string, unknown>
    featureFlags: FeatureFlagsSet
    objectType: string
    search: string
    page: number
    order: string
    objects: { results: FileSystemEntry[]; count: number }
    objectsLoading: boolean
    error: boolean
    objectTypes: { value: string; label: string }[]
    tools: FileSystemImport[]
    visibleTools: FileSystemImport[]
    toolCategories: string[]
    objectView: FileSystemImport | undefined
}

export interface desktopCatalogLogicActions {
    setFilters: (filters: Record<string, string | number>) => { filters: Record<string, string | number> }
    loadObjects: () => void
}

export type desktopCatalogLogicType = MakeLogicType<desktopCatalogLogicValues, desktopCatalogLogicActions>

export const desktopCatalogLogic = kea<desktopCatalogLogicType>([
    path(['layout', 'navigation-3000', 'desktopCatalogLogic']),
    connect(() => ({ values: [router, ['searchParams'], featureFlagLogic, ['featureFlags']] })),
    actions({ setFilters: (filters: Record<string, string | number>) => ({ filters }) }),
    loaders(({ values, cache }) => ({
        objects: [
            { results: [], count: 0 } as { results: FileSystemEntry[]; count: number },
            {
                loadObjects: async (_, breakpoint) => {
                    await breakpoint(250)
                    cache.unfiled ??= api.fileSystem.unfiled().catch((error: unknown) => {
                        cache.unfiled = undefined
                        throw error
                    })
                    await cache.unfiled
                    breakpoint()
                    const response = await api.fileSystem.list({
                        search: values.search,
                        notType: 'folder',
                        ...(values.objectType === 'insight'
                            ? { type__startswith: 'insight' }
                            : values.objectType
                              ? { type: values.objectType }
                              : {}),
                        orderBy: values.order,
                        offset: values.page * LIBRARY_PAGE_SIZE,
                        limit: LIBRARY_PAGE_SIZE,
                    })
                    breakpoint()
                    return { results: response.results, count: response.count }
                },
            },
        ],
    })),
    reducers({ error: [false, { loadObjects: () => false, loadObjectsFailure: () => true }] }),
    selectors({
        objectView: [
            (s) => [s.objectType, s.featureFlags],
            (objectType: string, flags: FeatureFlagsSet): FileSystemImport | undefined =>
                [...getTreeItemsProducts(), ...getTreeItemsMetadata()].find(
                    (item) =>
                        (item.type === objectType ||
                            item.iconType === objectType ||
                            (objectType === 'insight' && item.type === 'product_analytics')) &&
                        !!item.href &&
                        !!desktopObjectHref(item) &&
                        (!item.flag || flags[item.flag as keyof FeatureFlagsSet]) &&
                        !getProductAccessDisabledReason(item)
                ),
        ],
        objectType: [(s) => [s.searchParams], (params): string => String(params.library_type || '')],
        search: [(s) => [s.searchParams], (params): string => String(params.library_search || '')],
        page: [(s) => [s.searchParams], (params): number => Math.max(0, Math.floor(Number(params.library_page) || 0))],
        order: [
            (s) => [s.searchParams],
            (params): string => (params.library_order === 'path' ? 'path' : '-created_at'),
        ],
        objectTypes: [
            (s) => [s.featureFlags],
            (flags: FeatureFlagsSet): { value: string; label: string }[] =>
                Object.entries(fileSystemTypes)
                    .filter(([type, entry]) => !TOOL_TYPES.has(type) && (!('flag' in entry) || flags[entry.flag]))
                    .map(([value, entry]) => ({ value, label: entry.name }))
                    .sort((first, second) => first.label.localeCompare(second.label)),
        ],
        tools: [
            (s) => [s.featureFlags],
            (flags: FeatureFlagsSet): FileSystemImport[] => {
                const seen = new Set<string>()
                return [...getTreeItemsProducts(), ...getTreeItemsMetadata()]
                    .filter((item) => {
                        const type = item.type?.split('/')[0] || item.iconType || ''
                        if (
                            !item.href ||
                            seen.has(item.href) ||
                            !desktopObjectHref(item) ||
                            (type in fileSystemTypes && !TOOL_TYPES.has(type)) ||
                            (item.flag && !flags[item.flag as keyof FeatureFlagsSet]) ||
                            getProductAccessDisabledReason(item)
                        ) {
                            return false
                        }
                        seen.add(item.href)
                        return true
                    })
                    .sort((first, second) => first.path.localeCompare(second.path))
            },
        ],
        visibleTools: [
            (s) => [s.tools, s.search, s.objectType],
            (tools: FileSystemImport[], search: string, category: string): FileSystemImport[] =>
                tools.filter(
                    (item) =>
                        (!category || item.category === category) &&
                        `${item.path} ${item.category ?? ''}`.toLowerCase().includes(search.toLowerCase())
                ),
        ],
        toolCategories: [
            (s) => [s.tools],
            (tools: FileSystemImport[]): string[] =>
                [
                    ...new Set(tools.map((item) => item.category).filter((category): category is string => !!category)),
                ].sort(),
        ],
    }),
    listeners(({ actions }) => ({
        setFilters: ({ filters }) => {
            router.actions.push(urls.projectHomepage(), { ...router.values.searchParams, library_page: 0, ...filters })
        },
        [router.actionTypes.locationChanged]: () => {
            if (classicEmbedContext?.section === 'library' && router.values.location.pathname.endsWith('/home')) {
                actions.loadObjects()
            }
        },
    })),
    afterMount(({ actions }) => {
        if (classicEmbedContext?.section === 'library') {
            actions.loadObjects()
        }
    }),
])
