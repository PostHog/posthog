import { afterMount, connect, kea, key, path, props, selectors } from 'kea'

import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { notebooksModel } from '~/models/notebooksModel'
import { ActivityScope, Breadcrumb, ProjectTreeRef } from '~/types'

import { notebookLogic } from './Notebook/notebookLogic'
import type { notebookSceneLogicType } from './notebookSceneLogicType'

export type NotebookSceneLogicProps = {
    shortId: string
}
export const notebookSceneLogic = kea<notebookSceneLogicType>([
    path((key) => ['scenes', 'notebooks', 'notebookSceneLogic', key]),
    props({} as NotebookSceneLogicProps),
    key(({ shortId }) => shortId),
    connect((props: NotebookSceneLogicProps) => ({
        values: [
            notebookLogic(props),
            ['notebook', 'notebookLoading', 'isLocalOnly'],
            notebooksModel,
            ['notebooksLoading'],
        ],
        actions: [notebookLogic(props), ['loadNotebook'], notebooksModel, ['createNotebook']],
    })),
    selectors(() => ({
        notebookId: [(_, p) => [p.shortId], (shortId) => shortId],

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
                    iconType: 'notebook',
                },
                {
                    key: [Scene.Notebook, notebook?.short_id || 'new'],
                    name: notebook ? notebook?.title || 'Unnamed' : loading ? null : 'Notebook not found',
                    iconType: 'notebook',
                },
            ],
        ],

        projectTreeRef: [
            () => [(_, props: NotebookSceneLogicProps) => props.shortId],
            (shortId): ProjectTreeRef | null => (shortId === 'new' ? null : { type: 'notebook', ref: String(shortId) }),
        ],

        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.notebookId, s.isLocalOnly],
            (notebookId, isLocalOnly): SidePanelSceneContext | null => {
                return notebookId && !isLocalOnly
                    ? {
                          activity_scope: ActivityScope.NOTEBOOK,
                          activity_item_id: notebookId,
                          access_control_resource: 'notebook',
                          access_control_resource_id: notebookId,
                      }
                    : null
            },
        ],
    })),

    afterMount(({ actions, props }) => {
        if (props.shortId !== 'new') {
            actions.loadNotebook()
        }
    }),
])
