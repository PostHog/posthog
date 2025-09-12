import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import { router } from 'kea-router'
import { actionToUrl } from 'kea-router'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DashboardTemplateScope, DashboardTemplateType, TemplateAvailabilityContext } from '~/types'

import type { dashboardTemplatesLogicType } from './dashboardTemplatesLogicType'

export interface DashboardTemplateProps {
    // default is to present global templates _and_ those visible only in the current team
    scope?: 'default' | DashboardTemplateScope
    onItemClick?: (template: DashboardTemplateType) => void
    redirectAfterCreation?: boolean
    availabilityContexts?: TemplateAvailabilityContext[]
}

export const dashboardTemplatesLogic = kea<dashboardTemplatesLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'templates', 'dashboardTemplatesLogic']),
    props({} as DashboardTemplateProps),
    key(({ scope }) => scope ?? 'unknown'),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setTemplates: (allTemplates: DashboardTemplateType[]) => ({ allTemplates }),
        setTemplateFilter: (search: string) => ({ search }),
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
    }),
    lazyLoaders(({ props, values }) => ({
        allTemplates: [
            [] as DashboardTemplateType[],
            {
                getAllTemplates: async () => {
                    const params = {
                        // the backend doesn't know about a default scope
                        scope: props.scope !== 'default' ? props.scope : undefined,
                        search: values.templateFilter.length > 2 ? values.templateFilter : undefined,
                    }
                    const page = await api.dashboardTemplates.list(params)
                    return page.results
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setTemplateFilter: async (_, breakpoint) => {
            await breakpoint(100)
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
