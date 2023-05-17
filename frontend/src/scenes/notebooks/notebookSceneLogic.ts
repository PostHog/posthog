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
        values: [notebookLogic(props), ['notebook']],
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
            (s) => [s.notebook],
            (notebook): Breadcrumb[] => [
                {
                    name: 'Notebooks',
                    path: urls.dashboards() + '?tab=notebooks',
                },
                {
                    name: notebook?.title || 'Unnamed',
                },
            ],
        ],
    })),
    urlToAction(({ actions, values }) => ({
        '/notebooks/:notebookId(/:mode)': (
            { mode } // url params
        ) =>
            // { dashboard, ...searchParams }, // search params
            // { filters: _filters, q }, // hash params
            // { method, initial } // "location changed" event payload
            {
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
    // beforeUnload(({ values }) => ({
    //     enabled: () => {
    //         const currentScene = sceneLogic.findMounted()?.values

    //         // safeguard against running this check on other scenes
    //         if (currentScene?.activeScene !== Scene.Insight) {
    //             return false
    //         }

    //         return (
    //             values.insightMode === ItemMode.Edit &&
    //             (!!values.insightLogicRef?.logic.values.insightChanged ||
    //                 !!values.insightDataLogicRef?.logic.values.queryChanged)
    //         )
    //     },
    //     message: 'Leave insight? Changes you made will be discarded.',
    //     onConfirm: () => {
    //         values.insightLogicRef?.logic.actions.cancelChanges()
    //         values.insightDataLogicRef?.logic.actions.cancelChanges()
    //     },
    // })),
])
