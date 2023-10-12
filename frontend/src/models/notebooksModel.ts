import { actions, BuiltLogic, connect, kea, path, reducers } from 'kea'

import { loaders } from 'kea-loaders'
import { NotebookListItemType, NotebookTarget, NotebookType } from '~/types'

import api from 'lib/api'
import posthog from 'posthog-js'
import { LOCAL_NOTEBOOK_TEMPLATES } from 'scenes/notebooks/NotebookTemplates/notebookTemplates'
import { deleteWithUndo } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { notebookPopoverLogic } from 'scenes/notebooks/Notebook/notebookPopoverLogic'
import { defaultNotebookContent, EditorFocusPosition, JSONContent } from 'scenes/notebooks/Notebook/utils'

import type { notebooksModelType } from './notebooksModelType'
import { notebookLogicType } from 'scenes/notebooks/Notebook/notebookLogicType'
import { urls } from 'scenes/urls'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { router } from 'kea-router'

export const SCRATCHPAD_NOTEBOOK: NotebookListItemType = {
    short_id: 'scratchpad',
    title: 'Scratchpad',
    created_at: '',
    created_by: null,
}

export const openNotebook = async (
    notebookId: string,
    target: NotebookTarget = NotebookTarget.Auto,
    focus: EditorFocusPosition | undefined = undefined,
    // operations to run against the notebook once it has opened and the editor is ready
    onOpen: (logic: BuiltLogic<notebookLogicType>) => void = () => {}
): Promise<void> => {
    const popoverLogic = notebookPopoverLogic.findMounted()

    if (NotebookTarget.Popover === target) {
        popoverLogic?.actions.setVisibility('visible')
    }

    if (popoverLogic?.values.visibility === 'visible') {
        popoverLogic?.actions.selectNotebook(notebookId, focus)
    } else {
        if (router.values.location.pathname === urls.notebook('new')) {
            router.actions.replace(urls.notebook(notebookId))
        } else {
            router.actions.push(urls.notebook(notebookId))
        }
    }

    const theNotebookLogic = notebookLogic({ shortId: notebookId })
    const unmount = theNotebookLogic.mount()

    try {
        onOpen(theNotebookLogic)
    } finally {
        unmount()
    }
}
export const notebooksModel = kea<notebooksModelType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebooksModel']),
    actions({
        setScratchpadNotebook: (notebook: NotebookListItemType) => ({ notebook }),
        createNotebook: (
            title?: string,
            location: NotebookTarget = NotebookTarget.Auto,
            content?: JSONContent[],
            onCreate?: (notebook: BuiltLogic<notebookLogicType>) => void
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

                    openNotebook(notebook.short_id, location, 'end', (logic) => {
                        onCreate?.(logic)
                    })

                    posthog.capture(`notebook created`, {
                        short_id: notebook.short_id,
                    })

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
])
