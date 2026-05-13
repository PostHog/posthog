import { kea, path, props, selectors } from 'kea'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { Breadcrumb } from '~/types'

import type { liveEventsTableSceneLogicType } from './liveEventsTableSceneLogicType'

export interface LiveEventsTableSceneProps {
    tabId?: string
}

export const liveEventsTableSceneLogic = kea<liveEventsTableSceneLogicType>([
    path(['scenes', 'activity', 'live-events', 'liveEventsTableSceneLogic']),
    props({} as LiveEventsTableSceneProps),
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
