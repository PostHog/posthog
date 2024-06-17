import { actions, kea, path, reducers } from 'kea'

import { ErrorTrackingOrder } from '~/queries/schema'

import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),

    actions({
        setOrder: (order: ErrorTrackingOrder) => ({ order }),
    }),
    reducers({
        order: [
            'last_seen' as ErrorTrackingOrder,
            { persist: true },
            {
                setOrder: (_, { order }) => order,
            },
        ],
    }),
])
