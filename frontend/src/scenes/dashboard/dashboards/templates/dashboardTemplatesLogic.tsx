import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import { router } from 'kea-router'
import { actionToUrl } from 'kea-router'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    DashboardTemplateListParams,
    DashboardTemplateScope,
    DashboardTemplateType,
    TemplateAvailabilityContext,
} from '~/types'

import type { dashboardTemplatesLogicType } from './dashboardTemplatesLogicType'

export interface DashboardTemplateProps {
    // default is to present global templates _and_ those visible only in the current team
    scope?: 'default' | DashboardTemplateScope
    onItemClick?: (template: DashboardTemplateType) => void
    redirectAfterCreation?: boolean
    availabilityContexts?: TemplateAvailabilityContext[]
    className?: string
}

export type DashboardTemplatesLogicProps = DashboardTemplateProps & {
    listQuery?: Partial<Pick<DashboardTemplateListParams, 'is_featured'>>
    /** When true, this logic instance is scoped to the Dashboards → Templates tab (visibility filter + refresh after edits). */
    templatesTabList?: boolean
}

export type DashboardTemplatesTabVisibility = 'all' | 'official' | 'project'

/** List sort for the templates table (passed through to API when not searching). */
export type DashboardTemplateTableOrdering = '' | 'template_name' | '-template_name' | 'created_at' | '-created_at'

/**
 * Mixed template lists (project + official): project-scoped rows first, then global/official.
 * Respects active table ordering when set; otherwise featured first, then A–Z by name (matches API defaults within each bucket).
 */
function sortTemplatesTeamScopeBeforeOfficial(
    templates: DashboardTemplateType[],
    ordering: DashboardTemplateTableOrdering
): DashboardTemplateType[] {
    const officialRank = (t: DashboardTemplateType): number => (t.scope === 'global' ? 1 : 0)

    return [...templates].sort((a, b) => {
        const scopeDiff = officialRank(a) - officialRank(b)
        if (scopeDiff !== 0) {
            return scopeDiff
        }
        if (ordering === 'template_name' || ordering === '-template_name') {
            const na = (a.template_name || '').toLowerCase()
            const nb = (b.template_name || '').toLowerCase()
            return ordering === '-template_name' ? nb.localeCompare(na) : na.localeCompare(nb)
        }
        if (ordering === 'created_at' || ordering === '-created_at') {
            const ta = dayjs(a.created_at || 0).valueOf()
            const tb = dayjs(b.created_at || 0).valueOf()
            return ordering === '-created_at' ? tb - ta : ta - tb
        }
        const fa = a.is_featured === true ? 1 : 0
        const fb = b.is_featured === true ? 1 : 0
        if (fa !== fb) {
            return fb - fa
        }
        const na = (a.template_name || '').toLowerCase()
        const nb = (b.template_name || '').toLowerCase()
        return na.localeCompare(nb)
    })
}

/** Kea key segment for listQuery.is_featured — false vs omitted only diverge for global-scoped lists (API treats them differently). */
function listQueryFeaturedKeySegment(p: DashboardTemplatesLogicProps): 'featured' | 'not-featured' | 'all' {
    if (p.listQuery?.is_featured === true) {
        return 'featured'
    }
    if (p.scope === 'global' && p.listQuery?.is_featured === false) {
        return 'not-featured'
    }
    return 'all'
}

export const dashboardTemplatesLogic = kea<dashboardTemplatesLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'templates', 'dashboardTemplatesLogic']),
    props({} as DashboardTemplatesLogicProps),
    key(
        (p: DashboardTemplatesLogicProps) =>
            `${p.scope ?? 'default'}-${listQueryFeaturedKeySegment(p)}${p.templatesTabList ? '-templatesTab' : ''}`
    ),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setTemplates: (allTemplates: DashboardTemplateType[]) => ({ allTemplates }),
        setTemplateFilter: (search: string) => ({ search }),
        setTemplateNameOrdering: (ordering: DashboardTemplateTableOrdering) => ({ ordering }),
        setTemplatesTabVisibility: (visibility: DashboardTemplatesTabVisibility) => ({ visibility }),
    }),
    reducers({
        templateFilter: [
            '' as string,
            {
                setTemplateFilter: (_, { search }) => {
                    return search
                },
            },
        ],
        templateNameOrdering: [
            '' as DashboardTemplateTableOrdering,
            {
                setTemplateNameOrdering: (_, { ordering }) => ordering,
            },
        ],
        // lazyLoaders has no "loaded" flag; empty API results must not look "unfetched" forever (see urlToAction /dashboard).
        allTemplatesLoaded: [
            false,
            {
                getAllTemplatesSuccess: () => true,
            },
        ],
        templatesTabVisibility: [
            'all' as DashboardTemplatesTabVisibility,
            {
                setTemplatesTabVisibility: (_, { visibility }) => visibility,
            },
        ],
    }),
    lazyLoaders(({ props, values }) => ({
        allTemplates: [
            [] as DashboardTemplateType[],
            {
                getAllTemplates: async () => {
                    const logicProps = props as DashboardTemplatesLogicProps
                    const featuredOnly = logicProps.listQuery?.is_featured === true
                    // Curated featured list (empty dashboards) must ignore `templateFilter` synced from the URL via
                    // `urlToAction` when the Templates tab or another surface leaves `?templateFilter=` on /dashboard.
                    const useSearch = !featuredOnly && values.templateFilter.length > 2

                    let listScope: DashboardTemplateScope | undefined
                    if (logicProps.scope !== 'default' && logicProps.scope !== undefined) {
                        listScope = logicProps.scope
                    } else if (logicProps.templatesTabList) {
                        if (values.templatesTabVisibility === 'official') {
                            listScope = 'global'
                        } else if (values.templatesTabVisibility === 'project') {
                            listScope = 'team'
                        } else {
                            listScope = undefined
                        }
                    } else {
                        listScope = undefined
                    }

                    const params: DashboardTemplateListParams = {
                        scope: listScope,
                        search: useSearch ? values.templateFilter : undefined,
                        // Search results are relevance-ranked; omit ordering (see API `dangerously_get_queryset`).
                        ordering: useSearch ? undefined : values.templateNameOrdering || undefined,
                        ...logicProps.listQuery,
                    }
                    const page = await api.dashboardTemplates.list(params)
                    if (!useSearch && listScope === undefined) {
                        return sortTemplatesTeamScopeBeforeOfficial(page.results, values.templateNameOrdering)
                    }
                    return page.results
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setTemplateFilter: async (_, breakpoint) => {
            await breakpoint(400)
            actions.getAllTemplates()
        },
        setTemplateNameOrdering: () => {
            actions.getAllTemplates()
        },
        setTemplatesTabVisibility: () => {
            actions.getAllTemplates()
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/dashboard': (_, searchParams) => {
            const raw = searchParams.templateFilter
            const filter = Array.isArray(raw) ? raw[0] : raw
            const next = typeof filter === 'string' ? filter : ''
            // Same value as URL: skip setTemplateFilter — its listener debounces and would refetch (modal flicker).
            if (values.templateFilter !== next) {
                actions.setTemplateFilter(next)
            } else if (!values.allTemplatesLoading && !values.allTemplatesLoaded) {
                actions.getAllTemplates()
            }
        },
    })),
    actionToUrl(({ values }) => ({
        setTemplateFilter: () => {
            const searchParams = { ...router.values.searchParams }
            searchParams.templateFilter = values.templateFilter
            if (!values.templateFilter) {
                delete searchParams.templateFilter
            }
            return ['/dashboard', searchParams, router.values.hashParams, { replace: true }]
        },
    })),
])
