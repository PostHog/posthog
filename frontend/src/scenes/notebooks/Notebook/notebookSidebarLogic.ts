import { actions, kea, reducers, path, listeners, connect } from 'kea'
import { NotebookNodeType } from '../Nodes/types'
import { notebookLogic } from './notebookLogic'

import type { notebookSidebarLogicType } from './notebookSidebarLogicType'
import { urlToAction } from 'kea-router'
import { notebooksListLogic } from './notebooksListLogic'
import { RefObject } from 'react'
import posthog from 'posthog-js'

export const notebookSidebarLogic = kea<notebookSidebarLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookSidebarLogic']),
    actions({
        setNotebookSideBarShown: (shown: boolean) => ({ shown }),
        setFullScreen: (full: boolean) => ({ full }),
        addNodeToNotebook: (type: NotebookNodeType, properties: Record<string, any>) => ({ type, properties }),
        selectNotebook: (id: string) => ({ id }),
        onResize: (event: { originX: number; desiredX: number; finished: boolean }) => event,
        setDesiredWidth: (width: number) => ({ width }),
        setElementRef: (element: RefObject<HTMLElement>) => ({ element }),
    }),

    connect({
        actions: [notebooksListLogic, ['createNotebookSuccess']],
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

        elementRef: [
            null as RefObject<HTMLElement> | null,
            {
                setElementRef: (_, { element }) => element,
            },
        ],
    })),

    listeners(({ values, actions, cache }) => ({
        setNotebookSideBarShown: ({ shown }) => {
            if (shown) {
                actions.setFullScreen(false)
            }

            posthog.capture(`notebook sidebar ${shown ? 'shown' : 'hidden'}`)
        },

        addNodeToNotebook: ({ type, properties }) => {
            notebookLogic({ shortId: values.selectedNotebook }).actions.addNodeToNotebook(type, properties)

            actions.setNotebookSideBarShown(true)
        },

        createNotebookSuccess: ({ notebooks }) => {
            // NOTE: This is temporary: We probably only want to select it if it is created from the sidebar
            actions.selectNotebook(notebooks[notebooks.length - 1].short_id)
        },

        onResize: ({ originX, desiredX, finished }) => {
            if (!values.elementRef?.current) {
                return
            }
            if (!cache.originalWidth) {
                cache.originalWidth = values.elementRef.current.getBoundingClientRect().width
            }

            if (finished) {
                cache.originalWidth = undefined
                actions.setDesiredWidth(values.elementRef.current.getBoundingClientRect().width)
            } else {
                actions.setDesiredWidth(cache.originalWidth - (desiredX - originX))
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
