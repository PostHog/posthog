import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { Breadcrumb } from '~/types'

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

    afterMount(({ actions }) => {
        actions.loadNotebook()
    }),
])
