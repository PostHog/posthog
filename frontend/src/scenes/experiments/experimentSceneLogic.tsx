import { actions, connect, kea, path, props, reducers, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb, Experiment, ProjectTreeRef } from '~/types'

import { type ExperimentLogicProps, NEW_EXPERIMENT, experimentLogic } from './experimentLogic'
import type { experimentSceneLogicType } from './experimentSceneLogicType'

export interface ExperimentSceneLogicProps extends ExperimentLogicProps {
    tabId?: string
}

export const experimentSceneLogic = kea<experimentSceneLogicType>([
    props({} as ExperimentSceneLogicProps),
    path(['scenes', 'experiments', 'experimentSceneLogic']),
    tabAwareScene(),
    connect((props: ExperimentLogicProps) => ({
        values: [experimentLogic(props), ['experiment', 'experimentMissing', 'isExperimentRunning']],
        actions: [experimentLogic(props), ['loadExperiment', 'loadExposures', 'setEditExperiment', 'resetExperiment']],
    })),
    actions({
        setActiveTabKey: (activeTabKey: string) => ({ activeTabKey }),
    }),
    reducers({
        activeTabKey: [
            'metrics' as string,
            {
                setActiveTabKey: (_, { activeTabKey }) => activeTabKey,
            },
        ],
    }),
    selectors({
        experimentId: [
            () => [(_, props) => props.experimentId ?? 'new'],
            (experimentId: Experiment['id']): Experiment['id'] => experimentId,
        ],
        formMode: [
            () => [(_, props) => props.formMode],
            (formMode: ExperimentLogicProps['formMode']): ExperimentLogicProps['formMode'] => formMode,
        ],
        breadcrumbs: [
            (s) => [s.experiment, s.experimentId],
            (experiment: Experiment, experimentId: Experiment['id']): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Experiments,
                        name: sceneConfigurations[Scene.Experiments].name || 'Experiments',
                        path: urls.experiments(),
                        iconType: sceneConfigurations[Scene.Experiments].iconType || 'default_icon_type',
                    },
                    {
                        key: [Scene.Experiment, experimentId],
                        name: experiment?.name || 'New Experiment',
                        iconType: sceneConfigurations[Scene.Experiment].iconType || 'default_icon_type',
                    },
                ]
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.experimentId],
            (experimentId: Experiment['id']): SidePanelSceneContext | null => {
                return experimentId && experimentId !== 'new'
                    ? {
                          activity_scope: ActivityScope.EXPERIMENT,
                          activity_item_id: `${experimentId}`,
                      }
                    : null
            },
        ],
        projectTreeRef: [
            (s) => [s.experimentId],
            (experimentId: Experiment['id']): ProjectTreeRef => {
                return { type: 'experiment', ref: experimentId === 'new' ? null : String(experimentId) }
            },
        ],
    }),
    tabAwareUrlToAction(({ actions, values }) => ({
        '/experiments/:id': ({ id }, query, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            actions.setEditExperiment(false)

            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)
                if (parsedId === 'new') {
                    actions.resetExperiment({
                        ...NEW_EXPERIMENT,
                        metrics: query.metric ? [query.metric] : [],
                        name: query.name ?? '',
                    })
                } else {
                    // Only load if this is a different experiment or initial load
                    const shouldLoad = currentLocation.initial || values.experiment?.id !== parsedId

                    if (shouldLoad) {
                        actions.loadExperiment()
                    }

                    if (values.isExperimentRunning) {
                        actions.loadExposures()
                    }
                }
            }
        },
        '/experiments/:id/:formMode': ({ id, formMode }, _, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            if (id && didPathChange) {
                const parsedId = id === 'new' ? 'new' : parseInt(id)

                // For form modes, always reload to ensure proper data transformation (duplicate/edit)
                // unless we're just switching back to a tab that already has this exact experiment+formMode loaded
                const shouldLoad =
                    currentLocation.initial || values.experiment?.id !== parsedId || values.formMode !== formMode

                if (shouldLoad) {
                    actions.loadExperiment()
                }
            }
        },
    })),
])
