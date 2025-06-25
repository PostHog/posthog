import { actions, kea, path, reducers } from 'kea'

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
])
