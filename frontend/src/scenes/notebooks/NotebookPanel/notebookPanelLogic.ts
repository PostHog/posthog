import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { draggableLinkLogic } from 'lib/components/DraggableLink/draggableLinkLogic'
import { EditorFocusPosition } from 'lib/components/RichContentEditor/types'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { NotebookNodeResource } from '../types'
import type { notebookPanelLogicType } from './notebookPanelLogicType'

export const notebookPanelLogic = kea<notebookPanelLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookPanelLogic']),

    connect(() => ({
        values: [sidePanelStateLogic, ['sidePanelOpen', 'selectedTab'], draggableLinkLogic, ['dropMode']],
        actions: [
            sidePanelStateLogic,
            ['openSidePanel', 'closeSidePanel'],
            draggableLinkLogic,
            ['startDropMode', 'endDropMode', 'setDroppedResource'],
        ],
    })),
    actions({
        selectNotebook: (id: string, options: { autofocus?: EditorFocusPosition; silent?: boolean } = {}) => ({
            id,
            ...options,
        }),
        setNotebookDroppedResource: (resource: NotebookNodeResource | string | null) => ({ resource }),
        toggleVisibility: true,
    }),

    reducers(() => ({
        selectedNotebook: [
            'scratchpad',
            { persist: true },
            {
                selectNotebook: (_, { id }) => id,
            },
        ],
        initialAutofocus: [
            'start' as EditorFocusPosition,
            {
                selectNotebook: (_, { autofocus }) => autofocus ?? 'start',
            },
        ],
        notebookDroppedResource: [
            null as NotebookNodeResource | string | null,
            {
                closeSidePanel: () => null,
                setNotebookDroppedResource: (_, { resource }) => resource,
            },
        ],
    })),

    selectors(() => ({
        visibility: [
            (s) => [s.selectedTab, s.sidePanelOpen],
            (selectedTab: SidePanelTab | null, sidePanelOpen: boolean): 'hidden' | 'visible' => {
                return selectedTab === SidePanelTab.Notebooks && sidePanelOpen ? 'visible' : 'hidden'
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        selectNotebook: (options) => {
            if (options.silent) {
                return
            }
            actions.openSidePanel(SidePanelTab.Notebooks)
        },
        toggleVisibility: () => {
            if (values.visibility === 'hidden') {
                actions.openSidePanel(SidePanelTab.Notebooks)
            } else {
                actions.closeSidePanel()
            }
        },
    })),
])
