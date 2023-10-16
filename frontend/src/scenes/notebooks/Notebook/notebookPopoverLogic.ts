import { actions, kea, reducers, path, listeners, selectors } from 'kea'

import { urlToAction } from 'kea-router'
import { HTMLProps, RefObject } from 'react'
import posthog from 'posthog-js'
import { subscriptions } from 'kea-subscriptions'
import { EditorFocusPosition } from './utils'

import type { notebookPopoverLogicType } from './notebookPopoverLogicType'
import { NotebookNodeResource, NotebookPopoverVisibility } from '~/types'

export const MIN_NOTEBOOK_SIDEBAR_WIDTH = 600

export const notebookPopoverLogic = kea<notebookPopoverLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookPopoverLogic']),
    actions({
        setFullScreen: (full: boolean) => ({ full }),
        selectNotebook: (id: string, autofocus: EditorFocusPosition | undefined = undefined) => ({ id, autofocus }),
        setElementRef: (element: RefObject<HTMLElement>) => ({ element }),
        setVisibility: (visibility: NotebookPopoverVisibility) => ({ visibility }),
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
        visibility: [
            'hidden' as NotebookPopoverVisibility,
            {
                setVisibility: (_, { visibility }) => visibility,
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
            (s) => [s.dropMode, s.visibility, s.dropDistance],
            (
                dropMode,
                visibility,
                dropDistance
            ): Pick<HTMLProps<HTMLDivElement>, 'onDragEnter' | 'onDragLeave' | 'style'> => {
                return dropMode
                    ? {
                          onDragEnter: () => {
                              cache.dragEntercount = (cache.dragEntercount || 0) + 1
                              if (cache.dragEntercount === 1) {
                                  actions.setVisibility('visible')
                              }
                          },

                          onDragLeave: () => {
                              cache.dragEntercount = (cache.dragEntercount || 0) - 1

                              if (cache.dragEntercount <= 0) {
                                  cache.dragEntercount = 0
                                  actions.setVisibility('peek')
                              }
                          },
                          style: {
                              transform: visibility === 'peek' ? `translateX(${(1 - dropDistance) * 100}%)` : undefined,
                          },
                      }
                    : {}
            },
        ],
    })),

    subscriptions({
        visibility: (value, oldvalue) => {
            if (oldvalue !== undefined && value !== oldvalue) {
                posthog.capture(`notebook sidebar ${value}`)
            }
        },
    }),

    listeners(({ cache, actions, values }) => ({
        startDropMode: () => {
            cache.dragEntercount = 0
            cache.dragStart = null
            actions.setVisibility('peek')

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
            if (values.visibility === 'peek') {
                actions.setVisibility('hidden')
            }
            window.removeEventListener('drag', cache.dragListener)
        },
    })),

    urlToAction(({ actions, values }) => ({
        '/*': () => {
            // Any navigation should trigger exiting full screen
            if (values.visibility === 'visible') {
                actions.setVisibility('hidden')
            }
        },
    })),
])
