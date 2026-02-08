import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { Breadcrumb } from '~/types'

import type { destinationsSceneLogicType } from './destinationsSceneLogicType'

export const destinationsSceneLogic = kea<destinationsSceneLogicType>([
    path(['scenes', 'data-pipelines', 'destinationsSceneLogic']),
    actions({
        setActiveTab: (tab: 'all' | 'history') => ({ tab }),
    }),
    reducers({
        activeTab: [
            'all' as 'all' | 'history',
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),
    actionToUrl(({ values }) => ({
        setActiveTab: () => {
            const searchParams = values.activeTab === 'history' ? { tab: 'history' } : {}
            return [router.values.location.pathname, searchParams, router.values.hashParams]
        },
    })),
    urlToAction(({ actions }) => ({
        '/data-management/destinations': (_, searchParams) => {
            const tab = searchParams.tab === 'history' ? 'history' : 'all'
            actions.setActiveTab(tab)
        },
    })),
    {
        selectors: {
            breadcrumbs: [
                () => [],
                (): Breadcrumb[] => {
                    return [
                        {
                            key: 'Destinations',
                            name: 'Destinations',
                            iconType: 'data_pipeline',
                        },
                    ]
                },
            ],
        },
    },
])
