import { actions, kea, reducers, path, selectors, connect } from 'kea'
import { navigationLogic } from '~/layout/navigation/navigationLogic'

import type { notebookSidebarLogicType } from './notebookSidebarLogicType'

export const notebookSidebarLogic = kea<notebookSidebarLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookSidebarLogic']),
    connect(() => ({
        values: [navigationLogic, ['mobileLayout', 'bareNav']],
    })),
    actions({
        toggleNotebookSideBarBase: (override?: boolean) => ({ override }), // Only use the override for testing
        toggleNotebookSideBarMobile: (override?: boolean) => ({ override }), // Only use the override for testing
        showNotebookSideBarBase: true,
        hideNotebookSideBarBase: true,
        hideNotebookSideBarMobile: true,
    }),
    reducers(() => ({
        // Non-mobile base
        isNotebookSideBarShownBase: [
            false,
            { persist: true },
            {
                showNotebookSideBarBase: () => true,
                hideNotebookSideBarBase: () => false,
                toggleNotebookSideBarBase: (state, { override }) => override ?? !state,
            },
        ],
        // Mobile, applied on top of base, so that the sidebar does not show up annoyingly when shrinking the window
        isNotebookSideBarShownMobile: [
            false,
            {
                toggleNotebookSideBarMobile: (state, { override }) => override ?? !state,
                hideNotebookSideBarMobile: () => false,
            },
        ],
    })),
    selectors({
        isNotebookSideBarShown: [
            (s) => [s.mobileLayout, s.isNotebookSideBarShownBase, s.isNotebookSideBarShownMobile, s.bareNav],
            (mobileLayout, isNotebookSideBarShownBase, isNotebookSideBarShownMobile, bareNav) =>
                !bareNav && (mobileLayout ? isNotebookSideBarShownMobile : isNotebookSideBarShownBase),
        ],
    }),
])
