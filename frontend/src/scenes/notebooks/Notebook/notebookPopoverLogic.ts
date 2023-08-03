import { actions, kea, reducers, path, listeners, selectors } from 'kea'

import { urlToAction } from 'kea-router'
import { RefObject } from 'react'
import posthog from 'posthog-js'
import { subscriptions } from 'kea-subscriptions'
import { EditorFocusPosition } from './utils'

import type { notebookPopoverLogicType } from './notebookPopoverLogicType'
import { NotebookPopoverVisibility } from '~/types'

export const MIN_NOTEBOOK_SIDEBAR_WIDTH = 600

export const notebookPopoverLogic = kea<notebookPopoverLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookPopoverLogic']),
    actions({
        setFullScreen: (full: boolean) => ({ full }),
        selectNotebook: (id: string) => ({ id }),
        setInitialAutofocus: (position: EditorFocusPosition) => ({ position }),
        setElementRef: (element: RefObject<HTMLElement>) => ({ element }),
        setVisibility: (visibility: NotebookPopoverVisibility) => ({ visibility }),
        startDropMode: true,
        endDropMode: true,
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
            null as EditorFocusPosition,
            {
                selectNotebook: () => null,
                setInitialAutofocus: (_, { position }) => position,
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
    })),

    selectors(({ cache, actions }) => ({
        dropListeners: [
            (s) => [s.dropMode],
            (dropMode): Pick<React.HTMLAttributes<HTMLElement>, 'onDragEnter' | 'onDragLeave'> => {
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
            actions.setVisibility('peek')
        },
        endDropMode: () => {
            if (values.visibility === 'peek') {
                actions.setVisibility('hidden')
            }
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
