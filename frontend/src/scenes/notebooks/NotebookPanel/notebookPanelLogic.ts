import { actions, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { HTMLProps } from 'react'

import { EditorFocusPosition } from 'lib/components/RichContentEditor/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { NotebookNodeResource } from '../types'
import type { notebookPanelLogicType } from './notebookPanelLogicType'

export const notebookPanelLogic = kea<notebookPanelLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookPanelLogic']),
    connect(() => ({
        values: [sidePanelStateLogic, ['sidePanelOpen', 'selectedTab'], featureFlagLogic, ['featureFlags']],
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
    })),
    actions({
        selectNotebook: (id: string, options: { autofocus?: EditorFocusPosition; silent?: boolean } = {}) => ({
            id,
            ...options,
        }),
        startDropMode: true,
        endDropMode: true,
        setDroppedResource: (resource: NotebookNodeResource | string | null) => ({ resource }),
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
        dropMode: [
            false,
            {
                startDropMode: () => true,
                endDropMode: () => false,
            },
        ],
        droppedResource: [
            null as NotebookNodeResource | string | null,
            {
                closeSidePanel: () => null,
                setDroppedResource: (_, { resource }) => resource,
            },
        ],
    })),

    selectors(({ cache, actions }) => ({
        visibility: [
            (s) => [s.selectedTab, s.sidePanelOpen],
            (selectedTab, sidePanelOpen): 'hidden' | 'visible' => {
                return selectedTab === SidePanelTab.Notebooks && sidePanelOpen ? 'visible' : 'hidden'
            },
        ],

        dropProperties: [
            (s) => [s.dropMode],
            (dropMode): Pick<HTMLProps<HTMLDivElement>, 'onDragEnter' | 'onDragLeave' | 'style'> => {
                return dropMode
                    ? {
                          onDragEnter: () => {
                              cache.dragEntercount = (cache.dragEntercount || 0) + 1
                              if (cache.dragEntercount === 1) {
                                  actions.openSidePanel(SidePanelTab.Notebooks)
                              }
                          },

                          onDragLeave: () => {
                              cache.dragEntercount = (cache.dragEntercount || 0) - 1

                              if (cache.dragEntercount <= 0) {
                                  cache.dragEntercount = 0
                              }
                          },
                      }
                    : {}
            },
        ],
    })),

    listeners(({ cache, actions, values }) => ({
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
        startDropMode: () => {
            cache.dragEntercount = 0
            cache.dragStart = null

            cache.initialPanelState = {
                sidePanelOpen: values.sidePanelOpen,
                selectedTab: values.selectedTab,
            }

            cache.dragListener = (event: MouseEvent) => {
                if (!cache.dragStart) {
                    cache.dragStart = event.pageX
                }

                // The drop distance is the percentage between where the drag started and where it now is
                const distanceFromRightEdge = window.innerWidth - event.pageX
                const distanceFromDragStart = event.pageX - cache.dragStart

                // If we have dragged a little bit to the right, or we are dragging close to the side panel
                const shouldBeOpen = distanceFromDragStart > 50 || distanceFromRightEdge < 200

                if (shouldBeOpen && (!values.sidePanelOpen || values.selectedTab !== SidePanelTab.Notebooks)) {
                    actions.openSidePanel(SidePanelTab.Notebooks)
                } else if (!cache.initialPanelState.sidePanelOpen && !shouldBeOpen) {
                    actions.closeSidePanel()
                }
            }
            window.addEventListener('drag', cache.dragListener)
        },
        endDropMode: () => {
            // If we are in the notebook panel then we leave it open, otherwise we revert to the original state
            if (cache.dragEntercount <= 0) {
                if (!cache.initialPanelState.sidePanelOpen) {
                    actions.closeSidePanel()
                } else {
                    actions.openSidePanel(cache.initialPanelState.selectedTab)
                }
            }
            window.removeEventListener('drag', cache.dragListener)
        },
    })),

    beforeUnmount(({ cache }) => {
        // Clean up any active drag listener if component unmounts during drag
        if (cache.dragListener) {
            window.removeEventListener('drag', cache.dragListener)
        }
    }),
])
