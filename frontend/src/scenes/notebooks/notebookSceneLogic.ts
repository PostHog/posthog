import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { Breadcrumb, NotebookMode } from '~/types'
import { actionToUrl, urlToAction } from 'kea-router'

import type { notebookSceneLogicType } from './notebookSceneLogicType'
import { notebookLogic } from './Notebook/notebookLogic'
import { urls } from 'scenes/urls'

export type NotebookSceneLogicProps = {
    shortId: string
}
export const notebookSceneLogic = kea<notebookSceneLogicType>([
    path((key) => ['scenes', 'notebooks', 'notebookSceneLogic', key]),
    props({} as NotebookSceneLogicProps),
    key(({ shortId }) => shortId),
    connect((props: NotebookSceneLogicProps) => ({
        values: [notebookLogic(props), ['notebook', 'notebookLoading']],
        actions: [notebookLogic(props), ['loadNotebook']],
    })),
    actions({
        setNotebookMode: (mode: NotebookMode) => ({ mode }),
    }),
    reducers({
        mode: [
            NotebookMode.View as NotebookMode,
            {
                setNotebookMode: (_, { mode }) => mode,
            },
        ],
    }),
    selectors(() => ({
        notebookId: [() => [(_, props) => props], (props): string => props.shortId],

        breadcrumbs: [
            (s) => [s.notebook, s.notebookLoading],
            (notebook, notebookLoading): Breadcrumb[] => [
                {
                    name: 'Notebooks',
                    path: urls.dashboards() + '?tab=notebooks',
                },
                {
                    name: notebook
                        ? notebook?.title || 'Unnamed'
                        : notebookLoading
                        ? 'Loading...'
                        : 'Notebook not found',
                },
            ],
        ],
    })),
    urlToAction(({ props, actions, values }) => ({
        [`/notebooks/${props.shortId}(/:mode)`]: (
            { mode } // url params
        ) => {
            const newMode = mode === 'edit' ? NotebookMode.Edit : NotebookMode.View

            if (newMode !== values.mode) {
                actions.setNotebookMode(newMode)
            }
        },
    })),
    actionToUrl(({ values, props }) => {
        return {
            setNotebookMode: () => {
                return values.mode === NotebookMode.View
                    ? urls.notebook(props.shortId)
                    : urls.notebookEdit(props.shortId)
            },
        }
    }),

    afterMount(({ actions }) => {
        actions.loadNotebook()
    }),
])
