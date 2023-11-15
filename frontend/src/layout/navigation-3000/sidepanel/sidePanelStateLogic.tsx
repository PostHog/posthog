import { actions, kea, listeners, path, reducers } from 'kea'
import { SidePanelTab } from '~/types'

import type { sidePanelStateLogicType } from './sidePanelStateLogicType'

// The side panel imports a lot of other components so this allows us to avoid circular dependencies

export const sidePanelStateLogic = kea<sidePanelStateLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelStateLogic']),
    actions({
        openSidePanel: (tab: SidePanelTab) => ({ tab }),
        closeSidePanel: (tab?: SidePanelTab) => ({ tab }),
        setSidePanelOpen: (open: boolean) => ({ open }),
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
        // NOTE: We explicitly reference the actions instead of connecting so that people don't accidentally
        // use this logic instead of sidePanelStateLogic
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
