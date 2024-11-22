import { actions, kea, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { featureManagementLogicType } from './featureManagementLogicType'
import {
    FEATURE_MANAGEMENT_SCENE_IDS,
    FEATURE_MANAGEMENT_SCENES,
    FEATURE_MANAGEMENT_SCENES_MAP,
    FeatureManagementScene,
    FeatureManagementSceneId,
} from './FeatureManagementScenes'

export const featureManagementLogic = kea<featureManagementLogicType>([
    props({}),
    path(['scenes', 'feature-management', 'featureManagementLogic']),
    actions({
        setActiveScene: (activeScene: FeatureManagementScene) => ({ activeScene }),
    }),
    reducers({
        activeScene: [
            FEATURE_MANAGEMENT_SCENES[0],
            {
                setActiveScene: (_, { activeScene }) => activeScene,
            },
        ],
    }),
    selectors({
        scenes: [() => [], () => FEATURE_MANAGEMENT_SCENES],
        breadcrumbs: [
            (s) => [s.activeScene, s.scenes],
            (activeScene, scenes): Breadcrumb[] => [
                {
                    key: Scene.FeatureManagement,
                    name: 'Feature management',
                    path: urls.featureManagement('features'),
                },
                {
                    key: [Scene.FeatureManagement, activeScene.id],
                    name: scenes.find((scene) => scene.id === activeScene.id)?.title,
                },
            ],
        ],
    }),
    actionToUrl({
        setActiveScene: ({ activeScene }) => {
            return urls.featureManagement(activeScene.id)
        },
    }),
    urlToAction(({ actions, values }) => ({
        '/feature-management': () => {
            router.actions.push('/feature-management/features')
        },
        '/feature-management/:sceneId': ({ sceneId }) => {
            if (sceneId && values.activeScene.id !== sceneId) {
                if (sceneId in FEATURE_MANAGEMENT_SCENE_IDS) {
                    actions.setActiveScene(FEATURE_MANAGEMENT_SCENES_MAP[sceneId as FeatureManagementSceneId])
                } else {
                    actions.setActiveScene(FEATURE_MANAGEMENT_SCENES_MAP['features'])
                }
            }
        },
    })),
])
