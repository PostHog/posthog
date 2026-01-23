import { actions, kea, key, path, props, reducers } from 'kea'

import type { outputPaneLogicType } from './outputPaneLogicType'

export enum OutputTab {
    Results = 'results',
    Visualization = 'visualization',
    Variables = 'variables',
    Materialization = 'materialization',
    Endpoint = 'endpoint',
}

export interface OutputTabProps {
    tabId: string
}

export const outputPaneLogic = kea<outputPaneLogicType>([
    path(['data-warehouse', 'editor', 'outputPaneLogic']),
    props({} as OutputTabProps),
    key((props) => props.tabId),
    actions({
        setActiveTab: (tab: OutputTab) => ({ tab }),
        setResultsOpen: (isOpen: boolean) => ({ isOpen }),
        setVisualizationOpen: (isOpen: boolean) => ({ isOpen }),
    }),
    reducers({
        activeTab: [
            OutputTab.Results as OutputTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        isResultsOpen: [
            true,
            {
                setResultsOpen: (_, { isOpen }) => isOpen,
            },
        ],
        isVisualizationOpen: [
            true,
            {
                setVisualizationOpen: (_, { isOpen }) => isOpen,
            },
        ],
    }),
])
