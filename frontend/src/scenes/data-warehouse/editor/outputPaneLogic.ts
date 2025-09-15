import { actions, kea, path, reducers } from 'kea'
import { router, urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import type { outputPaneLogicType } from './outputPaneLogicType'

export enum OutputTab {
    Results = 'results',
    Visualization = 'visualization',
    Variables = 'variables',
    Materialization = 'materialization',
}

export const outputPaneLogic = kea<outputPaneLogicType>([
    path(['data-warehouse', 'editor', 'outputPaneLogic']),
    actions({
        setActiveTab: (tab: OutputTab) => ({ tab }),
    }),
    reducers({
        activeTab: [
            OutputTab.Results as OutputTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),
    urlToAction(({ actions }) => ({
        [urls.sqlEditor()]: async (_, __, hashParams) => {
            if (hashParams?.tab) {
                if (Object.values(OutputTab).includes(hashParams.tab as OutputTab)) {
                    actions.setActiveTab(hashParams.tab as OutputTab)
                } else {
                    delete hashParams['tab']
                    router.actions.replace(router.values.location.pathname, router.values.searchParams, hashParams)
                    actions.setActiveTab(OutputTab.Results)
                }
            }
        },
    })),
])
