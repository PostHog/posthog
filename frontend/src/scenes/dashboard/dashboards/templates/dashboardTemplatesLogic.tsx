import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import { router } from 'kea-router'
import { actionToUrl } from 'kea-router'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
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
    key((p: DashboardTemplatesLogicProps) => `${p.scope ?? 'default'}-${listQueryFeaturedKeySegment(p)}`),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setTemplates: (allTemplates: DashboardTemplateType[]) => ({ allTemplates }),
        setTemplateFilter: (search: string) => ({ search }),
        setTemplateNameOrdering: (ordering: '' | 'template_name' | '-template_name') => ({ ordering }),
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
            '' as '' | 'template_name' | '-template_name',
            {
                setTemplateNameOrdering: (_, { ordering }) => ordering,
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
                    const params: DashboardTemplateListParams = {
                        // the backend doesn't know about a default scope
                        scope: logicProps.scope !== 'default' ? logicProps.scope : undefined,
                        search: useSearch ? values.templateFilter : undefined,
                        // Search results are relevance-ranked; omit ordering (see API `dangerously_get_queryset`).
                        ordering: useSearch ? undefined : values.templateNameOrdering || undefined,
                        ...logicProps.listQuery,
                    }
                    const page = await api.dashboardTemplates.list(params)
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
    })),
    urlToAction(({ actions }) => ({
        '/dashboard': (_, searchParams) => {
            if (searchParams.templateFilter) {
                actions.setTemplateFilter(searchParams.templateFilter)
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
