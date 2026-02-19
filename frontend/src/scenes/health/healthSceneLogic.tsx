import { kea, path, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { Breadcrumb } from '~/types'

import type { healthSceneLogicType } from './healthSceneLogicType'

export const healthSceneLogic = kea<healthSceneLogicType>([
    path(['scenes', 'health', 'healthSceneLogic']),
    tabAwareScene(),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Health,
                    name: sceneConfigurations[Scene.Health].name,
                    iconType: sceneConfigurations[Scene.Health].iconType || 'default_icon_type',
                },
            ],
        ],
    }),
])
