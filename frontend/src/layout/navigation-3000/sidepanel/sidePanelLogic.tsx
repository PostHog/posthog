import { actions, kea, reducers, path, listeners } from 'kea'

import type { sidePanelLogicType } from './sidePanelLogicType'

export enum SidePanelTab {
    Notebooks = 'notebook',
    Feedback = 'feedback',
    Docs = 'docs',
}

export const sidePanelLogic = kea<sidePanelLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelLogic']),
    actions({
        setSidePanelOpen: (open: boolean) => ({ open }),
        openSidePanel: (tab: SidePanelTab) => ({ tab }),
        closeSidePanel: (tab?: SidePanelTab) => ({ tab }),
    }),

    reducers(() => ({
        selectedTab: [
            null as SidePanelTab | null,
            { persist: true },
            {
                openSidePanel: (_, { tab }) => tab,
            },
        ],
        sidePanelOpen: [
            false,
            { persist: true },
            {
                setSidePanelOpen: (_, { open }) => open,
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        openSidePanel: () => {
            actions.setSidePanelOpen(true)
        },
        closeSidePanel: ({ tab }) => {
            if (!tab) {
                // If we aren't specifiying the tab we always close
                actions.setSidePanelOpen(false)
            } else if (values.selectedTab === tab) {
                // Otherwise we only close it if the tab is the currently open one
                actions.setSidePanelOpen(false)
            }
        },
    })),
])
