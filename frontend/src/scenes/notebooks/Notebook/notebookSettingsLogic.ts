import { actions, kea, path, reducers } from 'kea'

import type { notebookSettingsLogicType } from './notebookSettingsLogicType'

// This logic contains settings that should persist across all notebooks
export const notebookSettingsLogic = kea<notebookSettingsLogicType>([
    path(['scenes', 'notebooks', 'notebooks', 'notebookSettingsLogic']),
    actions({
        setIsExpanded: (expanded: boolean) => ({ expanded }),
        setIsMarkdownExpanded: (expanded: boolean) => ({ expanded }),
        setShowKernelInfo: (showKernelInfo: boolean) => ({ showKernelInfo }),
        setShowSchemaBrowser: (showSchemaBrowser: boolean) => ({ showSchemaBrowser }),
        setShowTableOfContents: (showTOC: boolean) => ({ showTOC }),
    }),
    reducers(() => ({
        isExpanded: [
            false,
            { persist: true },
            {
                setIsExpanded: (_, { expanded }) => expanded,
            },
        ],
        isMarkdownExpanded: [
            true,
            { persist: true },
            {
                setIsMarkdownExpanded: (_, { expanded }) => expanded,
            },
        ],
        showKernelInfo: [
            false,
            {
                setShowKernelInfo: (_, { showKernelInfo }) => showKernelInfo,
            },
        ],
        showSchemaBrowser: [
            false,
            {
                setShowSchemaBrowser: (_, { showSchemaBrowser }) => showSchemaBrowser,
            },
        ],
        showTableOfContents: [
            false,
            {
                setShowTableOfContents: (_, { showTOC }) => showTOC,
            },
        ],
    })),
])
