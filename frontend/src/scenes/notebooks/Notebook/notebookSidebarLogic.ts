import { actions, kea, reducers, path, listeners } from 'kea'

import type { notebookSidebarLogicType } from './notebookSidebarLogicType'
import { urlToAction } from 'kea-router'
import { RefObject } from 'react'
import posthog from 'posthog-js'
import { subscriptions } from 'kea-subscriptions'
import { EditorFocusPosition } from './utils'

export const MIN_NOTEBOOK_SIDEBAR_WIDTH = 600

export const notebookSidebarLogic = kea<notebookSidebarLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookSidebarLogic']),
    actions({
        setNotebookSideBarShown: (shown: boolean) => ({ shown }),
        setFullScreen: (full: boolean) => ({ full }),
        selectNotebook: (id: string) => ({ id }),
        setInitialAutofocus: (position: EditorFocusPosition) => ({ position }),
        onResize: (event: { originX: number; desiredX: number; finished: boolean }) => event,
        setDesiredWidth: (width: number) => ({ width }),
        setElementRef: (element: RefObject<HTMLElement>) => ({ element }),
    }),

    reducers(() => ({
        selectedNotebook: [
            'scratchpad',
            { persist: true },
            {
                selectNotebook: (_, { id }) => id,
            },
        ],
        notebookSideBarShown: [
            false,
            { persist: true },
            {
                setNotebookSideBarShown: (_, { shown }) => shown,
            },
        ],
        fullScreen: [
            false,
            {
                setFullScreen: (_, { full }) => full,
                setNotebookSideBarShown: (state, { shown }) => (!shown ? false : state),
            },
        ],
        desiredWidth: [
            750,
            { persist: true },
            {
                setDesiredWidth: (_, { width }) => width,
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
    })),

    subscriptions({
        notebookSideBarShown: (value, oldvalue) => {
            if (oldvalue !== undefined && value !== oldvalue) {
                posthog.capture(`notebook sidebar ${value ? 'shown' : 'hidden'}`)
            }
        },
    }),

    listeners(({ values, actions, cache }) => ({
        onResize: ({ originX, desiredX, finished }) => {
            if (values.fullScreen) {
                actions.setFullScreen(false)
            }
            if (!values.elementRef?.current) {
                return
            }
            if (!cache.originalWidth) {
                cache.originalWidth = values.elementRef.current.getBoundingClientRect().width
            }

            if (window.innerWidth - desiredX < MIN_NOTEBOOK_SIDEBAR_WIDTH / 3) {
                actions.setNotebookSideBarShown(false)
                return
            } else if (!values.notebookSideBarShown) {
                actions.setNotebookSideBarShown(true)
            }

            if (finished) {
                cache.originalWidth = undefined
                actions.setDesiredWidth(
                    Math.max(MIN_NOTEBOOK_SIDEBAR_WIDTH, values.elementRef.current.getBoundingClientRect().width)
                )
            } else {
                actions.setDesiredWidth(
                    Math.max(MIN_NOTEBOOK_SIDEBAR_WIDTH, cache.originalWidth - (desiredX - originX))
                )
            }
        },
    })),

    urlToAction(({ actions }) => ({
        '/*': () => {
            // Any navigation should trigger exiting full screen
            actions.setFullScreen(false)
        },
    })),
])
