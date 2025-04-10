import { actions, connect, kea, path, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { Variable } from '~/queries/nodes/DataVisualization/types'

import { editorSidebarLogicType } from './editorSidebarLogicType'

export enum EditorSidebarTab {
    QueryDatabase = 'query_database',
    QueryVariables = 'query_variables',
    QueryInfo = 'query_info',
}

export const editorSidebarLogic = kea<editorSidebarLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'sidebar', 'editorSidebarLogic']),
    connect({
        values: [variablesLogic, ['variablesForInsight']],
    }),
    actions({
        setActiveTab: (tab: EditorSidebarTab) => ({ tab }),
        setPreviousVariableCount: (count: number) => ({ count }),
    }),
    reducers({
        activeTab: [
            EditorSidebarTab.QueryDatabase as EditorSidebarTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        previousVariableCount: [
            0 as number,
            {
                setPreviousVariableCount: (_, { count }) => count,
            },
        ],
    }),
    subscriptions(({ values, actions }) => ({
        variablesForInsight: (variables: Variable[]) => {
            if (variables.length > values.previousVariableCount) {
                actions.setActiveTab(EditorSidebarTab.QueryVariables)
            }

            actions.setPreviousVariableCount(variables.length)
        },
    })),
])
