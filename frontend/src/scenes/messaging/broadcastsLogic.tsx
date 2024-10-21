import { kea, path, reducers, selectors } from 'kea'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { broadcastsLogicType } from './broadcastsLogicType'

export const broadcastsLogic = kea<broadcastsLogicType>([
    path(['scenes', 'messaging', 'broadcastsLogic']),
    reducers({
        counter: [1, {}],
    }),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: Scene.MessagingBroadcasts,
                        name: 'Messaging',
                        path: urls.messagingBroadcasts(),
                    },
                    {
                        key: 'broadcasts',
                        name: 'Broadcasts',
                        path: urls.messagingBroadcasts(),
                    },
                ]
            },
        ],
    }),
])
