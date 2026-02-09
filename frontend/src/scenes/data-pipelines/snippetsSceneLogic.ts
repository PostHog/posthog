import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { Breadcrumb } from '~/types'

import type { snippetsSceneLogicType } from './snippetsSceneLogicType'

export const snippetsSceneLogic = kea<snippetsSceneLogicType>([
    path(['scenes', 'data-pipelines', 'snippetsSceneLogic']),
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
        '/snippets': (_, searchParams) => {
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
                            key: 'JS snippets',
                            name: 'JS snippets',
                            iconType: 'data_pipeline',
                        },
                    ]
                },
            ],
        },
    },
])
