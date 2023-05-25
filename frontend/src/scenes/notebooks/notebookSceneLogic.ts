import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { Breadcrumb, NotebookMode } from '~/types'
import { actionToUrl, urlToAction } from 'kea-router'

import type { notebookSceneLogicType } from './notebookSceneLogicType'
import { notebookLogic } from './Notebook/notebookLogic'
import { urls } from 'scenes/urls'

export type NotebookSceneLogicProps = {
    id: string | number
}
export const notebookSceneLogic = kea<notebookSceneLogicType>([
    path(['scenes', 'notebooks', 'notebookSceneLogic']),
    path((key) => ['scenes', 'notebooks', 'notebookSceneLogic', key]),
    props({} as NotebookSceneLogicProps),
    key(({ id }) => id),
    connect((props: NotebookSceneLogicProps) => ({
        values: [notebookLogic(props), ['notebook', 'notebookLoading']],
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
        notebookId: [() => [(_, props) => props], (props): string => props.id],

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
        [`/notebooks/${props.id}(/:mode)`]: (
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
                return values.mode === NotebookMode.View ? urls.notebook(props.id) : urls.notebookEdit(props.id)
            },
        }
    }),
])
