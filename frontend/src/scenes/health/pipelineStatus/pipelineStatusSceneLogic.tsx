import { kea, path, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { pipelineStatusSceneLogicType } from './pipelineStatusSceneLogicType'

export const pipelineStatusSceneLogic = kea<pipelineStatusSceneLogicType>([
    path(['scenes', 'health', 'pipelineStatus', 'pipelineStatusSceneLogic']),
    tabAwareScene(),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Health,
                    name: sceneConfigurations[Scene.Health].name,
                    path: urls.health(),
                },
                {
                    key: Scene.PipelineStatus,
                    name: sceneConfigurations[Scene.PipelineStatus].name,
                },
            ],
        ],
    }),
])
