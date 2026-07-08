import { kea, key, path, selectors } from 'kea'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { Breadcrumb } from '~/types'

import type { liveEventsTableSceneLogicType } from './liveEventsTableSceneLogicType'

export const liveEventsTableSceneLogic = kea<liveEventsTableSceneLogicType>([
    key(() => 'scene'),
    path((key) => ['scenes', 'activity', 'live-events', 'liveEventsTableSceneLogic', key]),
    selectors(() => ({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.LiveEvents,
                    name: sceneConfigurations[Scene.LiveEvents].name,
                    iconType: sceneConfigurations[Scene.LiveEvents].iconType,
                },
            ],
        ],
    })),
])
