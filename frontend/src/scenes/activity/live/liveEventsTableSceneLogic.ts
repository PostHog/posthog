import { connect, kea, path, props, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { Breadcrumb } from '~/types'

import { liveEventsLogic } from './liveEventsLogic'
import type { liveEventsTableSceneLogicType } from './liveEventsTableSceneLogicType'

export interface LiveEventsTableSceneProps {
    showLiveStreamErrorToast?: boolean
    tabId?: string
}

export const liveEventsTableSceneLogic = kea<liveEventsTableSceneLogicType>([
    path(['scenes', 'activity', 'live-events', 'liveEventsTableSceneLogic']),
    tabAwareScene(),
    props({} as LiveEventsTableSceneProps),
    connect(() => ({
        values: [liveEventsLogic, ['events', 'filters', 'streamPaused']],
        actions: [liveEventsLogic, ['pauseStream', 'resumeStream', 'setFilters', 'clearEvents']],
    })),
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
