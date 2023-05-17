import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { ItemMode, NotebookMode } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urlToAction } from 'kea-router'
import { teamLogic } from 'scenes/teamLogic'

import type { notebookSceneLogicType } from './notebookSceneLogicType'

export type NotebookSceneLogicProps = {
    id: string | number
}
export const notebookSceneLogic = kea<notebookSceneLogicType>([
    path(['scenes', 'notebooks', 'notebookSceneLogic']),
    path((key) => ['scenes', 'notebooks', 'notebookSceneLogic', key]),
    props({} as NotebookSceneLogicProps),
    key(({ id }) => id),
    connect({
        logic: [eventUsageLogic],
        values: [teamLogic, ['currentTeam']],
    }),
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

        // breadcrumbs: [
        //     (s) => [s.insight],
        //     (insight): Breadcrumb[] => [
        //         {
        //             name: 'Insights',
        //             path: urls.savedInsights(),
        //         },
        //         {
        //             name: insight?.name || insight?.derived_name || 'Unnamed',
        //         },
        //     ],
        // ],
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
    // actionToUrl(({ values }) => {
    //     // Use the browser redirect to determine state to hook into beforeunload prevention
    //     const actionToUrl = ({
    //         insightMode = values.insightMode,
    //         insightId = values.insightId,
    //     }: {
    //         insightMode?: ItemMode
    //         insightId?: InsightShortId | 'new' | null
    //     }): string | undefined =>
    //         insightId && insightId !== 'new'
    //             ? insightMode === ItemMode.View
    //                 ? urls.insightView(insightId)
    //                 : urls.insightEdit(insightId)
    //             : undefined

    //     return {
    //         setInsightId: actionToUrl,
    //         setInsightMode: actionToUrl,
    //     }
    // }),
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
