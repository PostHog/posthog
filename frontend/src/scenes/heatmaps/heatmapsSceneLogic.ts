import { kea, path, selectors } from 'kea'

import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { heatmapsSceneLogicType } from './heatmapsSceneLogicType'

export const heatmapsSceneLogic = kea<heatmapsSceneLogicType>([
    path(['scenes', 'heatmaps', 'heatmapsSceneLogic']),
    selectors(() => ({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Heatmaps,
                        name: sceneConfigurations[Scene.Heatmaps].name || 'Heatmaps',
                        path: urls.heatmaps(),
                        iconType: sceneConfigurations[Scene.Heatmaps].iconType || 'default_icon_type',
                    },
                ]
            },
        ],
    })),
])
