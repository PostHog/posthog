import { actions, kea, path, reducers } from 'kea'

import type { notebookSettingsLogicType } from './notebookSettingsLogicType'

// This logic contains settings that should persist across all notebooks
export const notebookSettingsLogic = kea<notebookSettingsLogicType>([
    path(['scenes', 'notebooks', 'notebooks', 'notebookSettingsLogic']),
    actions({
        setIsExpanded: (expanded: boolean) => ({ expanded }),
    }),
    reducers(() => ({
        isExpanded: [
            true,
            { persist: true },
            {
                setIsExpanded: (_, { expanded }) => expanded,
            },
        ],
    })),
])
