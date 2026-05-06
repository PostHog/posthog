import { afterMount, connect, kea, path, selectors } from 'kea'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { Breadcrumb } from '~/types'

import type { exportsSceneLogicType } from './exportsSceneLogicType'

export const exportsSceneLogic = kea<exportsSceneLogicType>([
    path(['scenes', 'exports', 'exportsSceneLogic']),
    tabAwareScene(),
    connect(() => ({
        actions: [exportsLogic, ['loadExports']],
    })),
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
    afterMount(({ actions }) => {
        actions.loadExports()
    }),
])
