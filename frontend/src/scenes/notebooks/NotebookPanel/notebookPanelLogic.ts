import { actions, kea, reducers, path, listeners, selectors, connect } from 'kea'

import { HTMLProps } from 'react'
import { EditorFocusPosition } from '../Notebook/utils'

import type { notebookPanelLogicType } from './notebookPanelLogicType'
import { NotebookNodeResource } from '~/types'
import { SidePanelTab, sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { notebookPopoverLogic } from './notebookPopoverLogic'

export const notebookPanelLogic = kea<notebookPanelLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookPanelLogic']),
    connect({
        values: [
            sidePanelLogic,
            ['sidePanelOpen', 'selectedTab'],
            featureFlagLogic,
            ['featureFlags'],
            notebookPopoverLogic,
            ['popoverVisibility'],
        ],
        actions: [sidePanelLogic, ['openSidePanel', 'closeSidePanel'], notebookPopoverLogic, ['setPopoverVisibility']],
    }),
    actions({
        selectNotebook: (id: string, autofocus: EditorFocusPosition | undefined = undefined) => ({ id, autofocus }),
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
        is3000: [(s) => [s.featureFlags], (featureFlags) => featureFlags[FEATURE_FLAGS.POSTHOG_3000]],

        visibility: [
            (s) => [s.selectedTab, s.sidePanelOpen, s.popoverVisibility, s.is3000],
            (selectedTab, sidePanelOpen, popoverVisibility, is3000): 'hidden' | 'peek' | 'visible' => {
                // NOTE: To be removed after 3000 release
                if (!is3000) {
                    return popoverVisibility
                }

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
            if (!values.is3000) {
                actions.setPopoverVisibility('visible')
                notebookPopoverLogic.actions.selectNotebook(options.id, options.autofocus)

                return
            }
            actions.openSidePanel(SidePanelTab.Notebooks)
        },
        toggleVisibility: () => {
            if (!values.is3000) {
                actions.setPopoverVisibility(values.popoverVisibility === 'visible' ? 'hidden' : 'visible')
                return
            }

            if (values.visibility === 'hidden') {
                actions.openSidePanel(SidePanelTab.Notebooks)
            } else {
                actions.closeSidePanel()
            }
        },
        startDropMode: () => {
            if (!values.is3000) {
                notebookPopoverLogic.actions.startDropMode()
                return
            }
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
            if (!values.is3000) {
                notebookPopoverLogic.actions.endDropMode()
                return
            }

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
])
