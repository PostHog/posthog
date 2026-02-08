import { actions, kea, path, reducers } from 'kea'

import type { addInsightsToNotebookModalLogicType } from './addInsightsToNotebookModalLogicType'

export const addInsightsToNotebookModalLogic = kea<addInsightsToNotebookModalLogicType>([
    path(['scenes', 'notebooks', 'AddInsightsToNotebookModal', 'addInsightsToNotebookModalLogic']),
    actions({
        openModal: (insertionPosition: number | null) => ({ insertionPosition }),
        closeModal: true,
    }),
    reducers({
        isAddInsightsToNotebookModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        insertionPosition: [
            null as number | null,
            {
                openModal: (_, { insertionPosition }) => insertionPosition,
                closeModal: () => null,
            },
        ],
    }),
])
