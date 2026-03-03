import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { Breadcrumb } from '~/types'

import type { webScriptsSceneLogicType } from './webScriptsSceneLogicType'

export const webScriptsSceneLogic = kea<webScriptsSceneLogicType>([
    path(['scenes', 'data-pipelines', 'webScriptsSceneLogic']),
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
            const { tab: _, ...otherParams } = router.values.searchParams
            const searchParams = values.activeTab === 'history' ? { ...otherParams, tab: 'history' } : otherParams
            return [router.values.location.pathname, searchParams, router.values.hashParams]
        },
    })),
    urlToAction(({ actions }) => ({
        '/web-scripts': (_, searchParams) => {
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
                            key: 'Web scripts',
                            name: 'Web scripts',
                            iconType: 'data_pipeline',
                        },
                    ]
                },
            ],
        },
    },
])
