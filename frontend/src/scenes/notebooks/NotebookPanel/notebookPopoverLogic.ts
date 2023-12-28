import { actions, kea, path, reducers } from 'kea'
import { urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { NotebookPopoverVisibility } from '~/types'

import type { notebookPopoverLogicType } from './notebookPopoverLogicType'

export const notebookPopoverLogic = kea<notebookPopoverLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebookPopoverLogic']),
    actions({
        setPopoverVisibility: (visibility: NotebookPopoverVisibility) => ({ visibility }),
    }),

    reducers(() => ({
        popoverVisibility: [
            'hidden' as NotebookPopoverVisibility,
            {
                setPopoverVisibility: (_, { visibility }) => visibility,
            },
        ],
    })),

    subscriptions({
        popoverVisibility: (value, oldvalue) => {
            if (oldvalue !== undefined && value !== oldvalue) {
                posthog.capture(`notebook sidebar ${value}`)
            }
        },
    }),

    urlToAction(({ actions, values }) => ({
        '/*': (_, __, ___, { pathname }, { pathname: previousPathname }) => {
            if (values.popoverVisibility === 'visible' && pathname != previousPathname) {
                actions.setPopoverVisibility('hidden')
            }
        },
    })),
])
