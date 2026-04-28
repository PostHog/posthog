import { kea, path, selectors } from 'kea'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { Breadcrumb } from '~/types'

import type { heatmapRecordingLogicType } from './heatmapRecordingLogicType'

export const heatmapRecordingLogic = kea<heatmapRecordingLogicType>([
    path(['scenes', 'heatmaps', 'scenes', 'heatmap', 'heatmapRecordingLogic']),
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
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({ settings_section: 'environment-heatmaps' }),
        ],
    })),
])
