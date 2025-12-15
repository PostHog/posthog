import { actions, kea, path, reducers } from 'kea'

import type { addInsightsToNotebookModalLogicType } from './addInsightsToNotebookModalLogicType'

export const addInsightsToNotebookModalLogic = kea<addInsightsToNotebookModalLogicType>([
    path(['scenes', 'notebooks', 'AddInsightsToNotebookModal', 'addInsightsToNotebookModalLogic']),
    actions({
        toggleIsAddInsightsToNotebookModalOpen: true,
    }),
    reducers({
        isAddInsightsToNotebookModalOpen: [
            false,
            {
                toggleIsAddInsightsToNotebookModalOpen: (state) => !state,
            },
        ],
    }),
])
