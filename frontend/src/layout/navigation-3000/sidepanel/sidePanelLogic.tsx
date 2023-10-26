import { IconNotebook, IconQuestion } from '@posthog/icons'
import { actions, kea, reducers, path, listeners } from 'kea'

import type { sidePanelLogicType } from './sidePanelLogicType'
import { notebookPopoverLogic } from 'scenes/notebooks/Notebook/notebookPopoverLogic'
import { SidePanelSupport } from './panels/SidePanelSupport'

export const MIN_NOTEBOOK_SIDEBAR_WIDTH = 600

export enum SidePanelTab {
    Notebooks = 'notebooks',
    Feedback = 'feedback',
}

// TODO: Fix any
export const SidePanelTabs: Record<SidePanelTab, { label: string; Icon: any; Content: any }> = {
    [SidePanelTab.Notebooks]: {
        label: 'Notebooks',
        Icon: IconNotebook,
        Content: () => <p>TODO</p>,
    },
    [SidePanelTab.Feedback]: {
        label: 'Feedback',
        Icon: IconQuestion,
        Content: SidePanelSupport,
    },
}

export const sidePanelLogic = kea<sidePanelLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelLogic']),
    actions({
        openSidePanel: (tab: SidePanelTab) => ({ tab }),
        closeSidePanel: true,
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
                openSidePanel: () => true,
                closeSidePanel: () => false,
            },
        ],
    })),

    listeners(() => ({
        openSidePanel: ({ tab }) => {
            // Super temorary
            if (tab === SidePanelTab.Notebooks) {
                notebookPopoverLogic.actions.setVisibility('visible')
            }
        },
    })),
])
