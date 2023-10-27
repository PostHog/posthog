import { actions, kea, reducers, path, listeners, selectors, connect } from 'kea'

import { HTMLProps, RefObject } from 'react'
import { EditorFocusPosition } from '../Notebook/utils'

import type { notebookPanelLogicType } from './notebookPanelLogicType'
import { NotebookNodeResource } from '~/types'
import { SidePanelTab, sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'

export const MIN_NOTEBOOK_SIDEBAR_WIDTH = 600

export const notebookPanelLogic = kea<notebookPanelLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookPanelLogic']),
    connect({
        values: [sidePanelLogic, ['sidePanelOpen']],
        actions: [sidePanelLogic, ['openSidePanel']],
    }),
    actions({
        setFullScreen: (full: boolean) => ({ full }),
        selectNotebook: (id: string, autofocus: EditorFocusPosition | undefined = undefined) => ({ id, autofocus }),
        startDropMode: true,
        endDropMode: true,
        setDropDistance: (distance: number) => ({ distance }),
        setDroppedResource: (resource: NotebookNodeResource | string | null) => ({ resource }),
    }),

    reducers(() => ({
        selectedNotebook: [
            'scratchpad',
            { persist: true },
            {
                selectNotebook: (_, { id }) => id,
            },
        ],
        fullScreen: [
            false,
            {
                setFullScreen: (_, { full }) => full,
                setVisibility: (state, { visibility }) => (visibility === 'hidden' ? false : state),
            },
        ],
        initialAutofocus: [
            'start' as EditorFocusPosition,
            {
                selectNotebook: (_, { autofocus }) => autofocus ?? 'start',
            },
        ],
        elementRef: [
            null as RefObject<HTMLElement> | null,
            {
                setElementRef: (_, { element }) => element,
            },
        ],
        shownAtLeastOnce: [
            false,
            {
                setVisibility: (state, { visibility }) => visibility !== 'hidden' || state,
            },
        ],
        dropMode: [
            false,
            {
                startDropMode: () => true,
                endDropMode: () => false,
            },
        ],
        dropDistance: [
            0,
            {
                startDropMode: () => -1,
                endDropMode: () => -1,
                setDropDistance: (_, { distance }) => distance,
            },
        ],
        droppedResource: [
            null as NotebookNodeResource | string | null,
            {
                setVisibility: (state, { visibility }) => (visibility === 'hidden' ? null : state),
                setDroppedResource: (_, { resource }) => resource,
            },
        ],
    })),

    selectors(({ cache, actions }) => ({
        dropProperties: [
            (s) => [s.dropMode, s.dropDistance, s.sidePanelOpen],
            (
                dropMode,
                dropDistance,
                sidePanelOpen
            ): Pick<HTMLProps<HTMLDivElement>, 'onDragEnter' | 'onDragLeave' | 'style'> => {
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
                                  actions.openSidePanel(SidePanelTab.Notebooks)
                              }
                          },
                      }
                    : {}
            },
        ],
    })),

    listeners(({ cache, actions }) => ({
        startDropMode: () => {
            cache.dragEntercount = 0
            cache.dragStart = null
            actions.openSidePanel(SidePanelTab.Notebooks)

            cache.dragListener = (event: MouseEvent) => {
                if (!cache.dragStart) {
                    cache.dragStart = event.pageX
                }

                // The drop distance is the percentage between where the drag started and where it now is
                const dropDistance = (event.pageX - cache.dragStart) / window.innerWidth
                actions.setDropDistance(dropDistance)
            }
            window.addEventListener('drag', cache.dragListener)
        },
        endDropMode: () => {
            // if (values.visibility === 'peek') {
            //     actions.setVisibility('hidden')
            // }
            window.removeEventListener('drag', cache.dragListener)
        },
    })),
])
