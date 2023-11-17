import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { Breadcrumb, NotebookTarget } from '~/types'

import type { notebookSceneLogicType } from './notebookSceneLogicType'
import { notebookLogic } from './Notebook/notebookLogic'
import { urls } from 'scenes/urls'
import { notebooksModel } from '~/models/notebooksModel'
import { Scene } from 'scenes/sceneTypes'

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
    selectors(({ props }) => ({
        notebookId: [() => [(_, props) => props], (props): string => props.shortId],

        loading: [
            (s) => [s.notebookLoading, s.notebooksLoading],
            (notebookLoading, notebooksLoading) => notebookLoading || notebooksLoading,
        ],

        breadcrumbs: [
            (s) => [s.notebook, s.loading],
            (notebook, loading): Breadcrumb[] => [
                {
                    key: Scene.Notebooks,
                    name: 'Notebooks',
                    path: urls.notebooks(),
                },
                {
                    key: notebook?.short_id || 'new',
                    name: notebook ? notebook?.title || 'Unnamed' : loading ? null : 'Notebook not found',
                    onRename: !notebook?.is_template
                        ? async (title: string) => {
                              await notebookLogic(props).asyncActions.renameNotebook(title)
                          }
                        : undefined,
                },
            ],
        ],
    })),

    afterMount(({ actions, props }) => {
        if (props.shortId === 'new') {
            actions.createNotebook(NotebookTarget.Scene)
        } else {
            actions.loadNotebook()
        }
    }),
])
