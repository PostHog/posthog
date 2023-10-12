import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { Breadcrumb } from '~/types'

import type { notebookSceneLogicType } from './notebookSceneLogicType'
import { notebookLogic } from './Notebook/notebookLogic'
import { urls } from 'scenes/urls'
import { notebooksModel } from '~/models/notebooksModel'

export type NotebookSceneLogicProps = {
    shortId: string
}
export const notebookSceneLogic = kea<notebookSceneLogicType>([
    path((key) => ['scenes', 'notebooks', 'notebookSceneLogic', key]),
    props({} as NotebookSceneLogicProps),
    key(({ shortId }) => shortId),
    connect((props: NotebookSceneLogicProps) => ({
        values: [notebookLogic(props), ['notebook', 'notebookLoading'], notebooksModel, ['notebooksLoading']],
        actions: [notebookLogic(props), ['loadNotebook'], notebooksModel, ['createNotebook']],
    })),
    selectors(() => ({
        notebookId: [() => [(_, props) => props], (props): string => props.shortId],

        loading: [
            (s) => [s.notebookLoading, s.notebooksLoading],
            (notebookLoading, notebooksLoading) => notebookLoading || notebooksLoading,
        ],

        breadcrumbs: [
            (s) => [s.notebook, s.loading],
            (notebook, loading): Breadcrumb[] => [
                {
                    name: 'Notebooks',
                    path: urls.notebooks(),
                },
                {
                    name: notebook ? notebook?.title || 'Unnamed' : loading ? 'Loading...' : 'Notebook not found',
                },
            ],
        ],
    })),

    afterMount(({ actions, props }) => {
        if (props.shortId === 'new') {
            actions.createNotebook()
        } else {
            actions.loadNotebook()
        }
    }),
])
