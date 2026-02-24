import { kea, path, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { Breadcrumb } from '~/types'

import type { exportsSceneLogicType } from './exportsSceneLogicType'

export const exportsSceneLogic = kea<exportsSceneLogicType>([
    path(['scenes', 'exports', 'exportsSceneLogic']),
    tabAwareScene(),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Exports,
                    name: sceneConfigurations[Scene.Exports].name,
                    iconType: sceneConfigurations[Scene.Exports].iconType || 'default_icon_type',
                },
            ],
        ],
    }),
])
