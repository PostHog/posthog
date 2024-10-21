import { kea, path, reducers, selectors } from 'kea'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { providersLogicType } from './providersLogicType'

export const providersLogic = kea<providersLogicType>([
    path(['scenes', 'messaging', 'providersLogic']),
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
                        key: 'providers',
                        name: 'Providers',
                        path: urls.messagingProviders(),
                    },
                ]
            },
        ],
    }),
])
