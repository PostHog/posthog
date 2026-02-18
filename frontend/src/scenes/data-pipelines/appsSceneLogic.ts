import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { Breadcrumb } from '~/types'

import type { appsSceneLogicType } from './appsSceneLogicType'

export const appsSceneLogic = kea<appsSceneLogicType>([
    path(['scenes', 'data-pipelines', 'appsSceneLogic']),
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
        '/apps': (_, searchParams) => {
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
                            key: 'Apps',
                            name: 'Apps',
                            iconType: 'data_pipeline',
                        },
                    ]
                },
            ],
        },
    },
])
