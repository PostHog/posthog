import { receiveTransaction } from '@tiptap/pm/collab'
import { Step } from '@tiptap/pm/transform'
import { actions, beforeUnmount, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { TTEditor } from 'lib/components/RichContentEditor/types'

import type { notebookCollabLogicType } from './notebookCollabLogicType'

export type NotebookCollabProps = {
    shortId: string
}

export const notebookCollabLogic = kea<notebookCollabLogicType>([
    props({} as NotebookCollabProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookCollabLogic', key]),
    key(({ shortId }) => shortId),

    actions({
        bindEditor: (editor: TTEditor) => ({ editor }),
        unbindEditor: true,
        rebaseFromSteps: (steps: Record<string, any>[], clientIDs: (string | number)[]) => ({
            steps,
            clientIDs,
        }),
    }),

    reducers({
        ttEditor: [
            null as TTEditor | null,
            {
                bindEditor: (_, { editor }) => editor,
                unbindEditor: () => null,
            },
        ],
    }),

    listeners(({ values }) => ({
        rebaseFromSteps: ({ steps, clientIDs }) => {
            const editor = values.ttEditor
            if (!editor || !steps.length) {
                return
            }
            try {
                const parsed = steps.map((s) => Step.fromJSON(editor.state.schema, s))
                const tr = receiveTransaction(editor.state, parsed, clientIDs, {
                    mapSelectionBackward: true,
                })
                editor.view.dispatch(tr)
            } catch (e) {
                posthog.captureException(e as Error, { action: 'notebook collab rebase' })
                lemonToast.error('Failed to sync notebook changes. Please reload the page.')
            }
        },
    })),

    beforeUnmount(({ actions }) => {
        actions.unbindEditor()
    }),
])
