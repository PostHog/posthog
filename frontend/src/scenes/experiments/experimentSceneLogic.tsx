import { actions, connect, kea, path, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb, Experiment, ProjectTreeRef } from '~/types'

import { NEW_EXPERIMENT, experimentLogic } from './experimentLogic'
import type { experimentSceneLogicType } from './experimentSceneLogicType'

export const experimentSceneLogic = kea<experimentSceneLogicType>([
    path(['scenes', 'experiments', 'experimentSceneLogic']),
    connect(() => ({
        values: [experimentLogic, ['experiment', 'experimentId', 'experimentMissing', 'isExperimentRunning']],
        actions: [experimentLogic, ['loadExperiment', 'loadExposures', 'setEditExperiment', 'resetExperiment']],
    })),
    actions({
        // Actions are delegated to experimentLogic
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.experiment, s.experimentId],
            (experiment, experimentId): Breadcrumb[] => {
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
            (experimentId): ProjectTreeRef => {
                return { type: 'experiment', ref: experimentId === 'new' ? null : String(experimentId) }
            },
        ],
    }),
    urlToAction(({ actions, values }) => ({
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
                }
                if (parsedId !== 'new' && parsedId === values.experimentId) {
                    actions.loadExperiment()
                    if (values.isExperimentRunning) {
                        actions.loadExposures()
                    }
                }
            }
        },
        '/experiments/:id/:formMode': ({ id }, _, __, currentLocation, previousLocation) => {
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            if (id && didPathChange) {
                actions.loadExperiment()
            }
        },
    })),
])
