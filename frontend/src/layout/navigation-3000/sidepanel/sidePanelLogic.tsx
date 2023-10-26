import { IconInfo, IconNotebook, IconQuestion } from '@posthog/icons'
import { actions, kea, reducers, path, listeners } from 'kea'

import type { sidePanelLogicType } from './sidePanelLogicType'
import { SidePanelSupport } from './panels/SidePanelSupport'
import { SidePanelDocs } from './panels/SidePanelDocs'
import { SidePanelNotebook } from './panels/SidePanelNotebook'

export const MIN_NOTEBOOK_SIDEBAR_WIDTH = 600

export enum SidePanelTab {
    Notebooks = 'notebook',
    Feedback = 'feedback',
    Docs = 'docs',
}

// TODO: Fix any
export const SidePanelTabs: Record<SidePanelTab, { label: string; Icon: any; Content: any }> = {
    [SidePanelTab.Notebooks]: {
        label: 'Notebook',
        Icon: IconNotebook,
        Content: SidePanelNotebook,
    },
    [SidePanelTab.Feedback]: {
        label: 'Feedback',
        Icon: IconQuestion,
        Content: SidePanelSupport,
    },
    [SidePanelTab.Docs]: {
        label: 'Docs',
        Icon: IconInfo,
        Content: SidePanelDocs,
    },
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
        desiredWidth: [
            null as number | null,
            { persist: true },
            {
                setDesiredWidth: (_, { open }) => open,
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
