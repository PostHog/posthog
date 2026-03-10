import { BuiltLogic, actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { EditorFocusPosition, JSONContent } from 'lib/components/RichContentEditor/types'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { addProductIntent } from 'lib/utils/product-intents'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import type { notebookLogicType } from 'scenes/notebooks/Notebook/notebookLogicType'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import { LOCAL_NOTEBOOK_TEMPLATES } from 'scenes/notebooks/NotebookTemplates/notebookTemplates'
import { NotebookListItemType, NotebookNodeType, NotebookTarget } from 'scenes/notebooks/types'
import { defaultNotebookContent } from 'scenes/notebooks/utils'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { deleteFromTree, getLastNewFolder, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { InsightVizNode, Node, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { DashboardType, QueryBasedInsightModel } from '~/types'

import type { notebooksModelType } from './notebooksModelType'

export const SCRATCHPAD_NOTEBOOK: NotebookListItemType = {
    id: 'scratchpad',
    short_id: 'scratchpad',
    title: 'My scratchpad',
    created_at: '',
    created_by: null,
}

export const openNotebook = async (
    notebookId: string,
    target: NotebookTarget,
    autofocus: EditorFocusPosition | undefined = undefined,
    onOpen?: (logic: BuiltLogic<notebookLogicType>) => void
): Promise<void> => {
    const thePanelLogic = notebookPanelLogic.findMounted()

    if (thePanelLogic && target === NotebookTarget.Popover) {
        thePanelLogic.actions.selectNotebook(notebookId, { autofocus })
    } else {
        if (router.values.location.pathname === urls.notebook('new')) {
            router.actions.replace(urls.notebook(notebookId))
        } else {
            router.actions.push(urls.notebook(notebookId))
        }
    }

    if (onOpen) {
        // Wait for the Notebook component to mount its logic instance before
        // dispatching operations. Previously we mounted a temporary instance
        // and called onOpen immediately, but async listeners (like
        // insertAfterLastNode) were killed when we unmounted the temporary
        // instance before they could complete.
        let called = false
        const startTime = Date.now()
        while (Date.now() - startTime < 5000) {
            const mountedLogic = notebookLogic.findMounted({ shortId: notebookId })
            if (mountedLogic) {
                onOpen(mountedLogic)
                called = true
                break
            }
            await new Promise((resolve) => setTimeout(resolve, 50))
        }
        if (!called) {
            console.warn('openNotebook: timed out waiting for logic to mount', notebookId)
        }
    }
}

export const notebooksModel = kea<notebooksModelType>([
    path(['scenes', 'notebooks', 'Notebook', 'notebooksModel']),
    actions({
        createNotebook: (
            location: NotebookTarget,
            title?: string,
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
        createNotebookFromDashboard: (dashboard: DashboardType<QueryBasedInsightModel>) => ({ dashboard }),
    }),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),

    reducers({
        scratchpadNotebook: [SCRATCHPAD_NOTEBOOK],
    }),

    loaders(({ values }) => ({
        notebooks: [
            [] as NotebookListItemType[],
            {
                createNotebook: async ({ title, location, content, onCreate }) => {
                    const notebook = await api.notebooks.create({
                        title,
                        content: defaultNotebookContent(title, content),
                        _create_in_folder: getLastNewFolder(),
                    })

                    await openNotebook(notebook.short_id, location, 'end', (logic) => {
                        onCreate?.(logic)
                    })

                    posthog.capture(`notebook created`, {
                        short_id: notebook.short_id,
                    })

                    void addProductIntent({
                        product_type: ProductKey.NOTEBOOKS,
                        intent_context: ProductIntentContext.NOTEBOOK_CREATED,
                    })

                    return [notebook, ...values.notebooks]
                },

                deleteNotebook: async ({ shortId, title }) => {
                    await deleteWithUndo({
                        endpoint: `projects/${values.currentProjectId}/notebooks`,
                        object: { name: title || shortId, id: shortId },
                        callback: (undo) => {
                            if (undo) {
                                refreshTreeItem('notebook', shortId)
                            } else {
                                deleteFromTree('notebook', shortId)
                            }
                        },
                    })

                    const panelLogic = notebookPanelLogic.findMounted()

                    if (panelLogic && panelLogic.values.selectedNotebook === shortId) {
                        panelLogic.actions.selectNotebook(SCRATCHPAD_NOTEBOOK.short_id, { silent: true })
                    }

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
            LOCAL_NOTEBOOK_TEMPLATES,
            {
                // In the future we can load these from remote
            },
        ],
    })),

    listeners(({ asyncActions }) => ({
        createNotebookFromDashboard: async ({ dashboard }) => {
            const queries = dashboard.tiles.reduce(
                (acc, tile) => {
                    if (!tile.insight) {
                        return acc
                    }
                    acc.push({
                        title: tile.insight.name,
                        query: tile.insight.query,
                    })
                    return acc
                },
                [] as { title: string; query: InsightVizNode | Node | null }[]
            )

            const resources = queries.map((x) => ({
                type: NotebookNodeType.Query,
                attrs: {
                    title: x.title,
                    query: x.query,
                },
            }))

            await asyncActions.createNotebook(NotebookTarget.Scene, dashboard.name + ' (copied)', resources)
        },
    })),
])
