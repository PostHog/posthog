import { actions, BuiltLogic, connect, kea, path, reducers, selectors } from 'kea'

import { loaders } from 'kea-loaders'
import { NotebookListItemType, NotebookTarget, NotebookType } from '~/types'

import type { notebooksListLogicType } from './notebooksListLogicType'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import api from 'lib/api'
import posthog from 'posthog-js'
import { LOCAL_NOTEBOOK_TEMPLATES } from '../NotebookTemplates/notebookTemplates'
import { deleteWithUndo } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import FuseClass from 'fuse.js'
import { notebookPopoverLogic } from './notebookPopoverLogic'
import { EditorFocusPosition, JSONContent, defaultNotebookContent } from './utils'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { notebookLogicType } from 'scenes/notebooks/Notebook/notebookLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface Fuse extends FuseClass<NotebookListItemType> {}

export const SCRATCHPAD_NOTEBOOK: NotebookListItemType = {
    short_id: 'scratchpad',
    title: 'Scratchpad',
    created_at: '',
    created_by: null,
}

export const openNotebook = async (
    notebookId: string,
    target: NotebookTarget = NotebookTarget.Auto,
    focus: EditorFocusPosition = null,
    // operations to run against the notebook once it has opened and the editor is ready
    onOpen: (logic: BuiltLogic<notebookLogicType>) => void = () => {}
): Promise<void> => {
    const popoverLogic = notebookPopoverLogic.findMounted()

    if (NotebookTarget.Popover === target) {
        popoverLogic?.actions.setVisibility('visible')
    }

    if (popoverLogic?.values.visibility === 'visible') {
        popoverLogic?.actions.selectNotebook(notebookId)
    } else {
        router.actions.push(urls.notebookEdit(notebookId))
    }

    popoverLogic?.actions.setInitialAutofocus(focus)

    const theNotebookLogic = notebookLogic({ shortId: notebookId })
    const unmount = theNotebookLogic.mount()

    try {
        await theNotebookLogic.asyncActions.editorIsReady()
        onOpen(theNotebookLogic)
    } finally {
        unmount()
    }
}

export const notebooksListLogic = kea<notebooksListLogicType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebooksListLogic']),
    actions({
        setScratchpadNotebook: (notebook: NotebookListItemType) => ({ notebook }),
        createNotebook: (
            title?: string,
            location: NotebookTarget = NotebookTarget.Auto,
            content?: JSONContent[],
            onCreate?: (notebook: NotebookType) => void
        ) => ({
            title,
            location,
            content,
            onCreate,
        }),
        receiveNotebookUpdate: (notebook: NotebookListItemType) => ({ notebook }),
        loadNotebooks: true,
        deleteNotebook: (shortId: NotebookListItemType['short_id'], title?: string) => ({ shortId, title }),
    }),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    reducers({
        scratchpadNotebook: [
            SCRATCHPAD_NOTEBOOK as NotebookListItemType,
            {
                setScratchpadNotebook: (_, { notebook }) => notebook,
            },
        ],
    }),

    loaders(({ actions, values }) => ({
        notebooks: [
            [] as NotebookListItemType[],
            {
                loadNotebooks: async (_, breakpoint) => {
                    // TODO: Support pagination
                    await breakpoint(100)
                    const res = await api.notebooks.list()
                    return res.results
                },
                createNotebook: async ({ title, location, content, onCreate }, breakpoint) => {
                    await breakpoint(100)

                    const notebook = await api.notebooks.create({
                        title,
                        content: defaultNotebookContent(title, content),
                    })

                    openNotebook(notebook.short_id, location, 'end')

                    posthog.capture(`notebook created`, {
                        short_id: notebook.short_id,
                    })

                    onCreate?.(notebook)
                    return [notebook, ...values.notebooks]
                },

                deleteNotebook: async ({ shortId, title }) => {
                    deleteWithUndo({
                        endpoint: `projects/${values.currentTeamId}/notebooks`,
                        object: { name: title || shortId, id: shortId },
                        callback: actions.loadNotebooks,
                    })

                    notebookPopoverLogic.findMounted()?.actions.selectNotebook(SCRATCHPAD_NOTEBOOK.short_id)

                    return values.notebooks.filter((n) => n.short_id !== shortId)
                },

                receiveNotebookUpdate: ({ notebook }) => {
                    if (notebook.is_template) {
                        return values.notebooks
                    }
                    return values.notebooks.filter((n) => n.short_id !== notebook.short_id).concat([notebook])
                },
            },
        ],
        notebookTemplates: [
            LOCAL_NOTEBOOK_TEMPLATES as NotebookType[],
            {
                // In the future we can load these from remote
            },
        ],
    })),

    selectors({
        fuse: [
            (s) => [s.notebooks],
            (notebooks): Fuse => {
                return new FuseClass<NotebookListItemType>(notebooks, {
                    keys: ['title'],
                    threshold: 0.3,
                })
            },
        ],
    }),
])
