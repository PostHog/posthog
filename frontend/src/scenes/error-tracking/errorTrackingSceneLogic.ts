import { actions, kea, path, reducers } from 'kea'

import { ErrorTrackingQuery } from '~/queries/schema'

import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),

    actions({
        setOrder: (order: ErrorTrackingQuery['order']) => ({ order }),
    }),
    reducers({
        order: [
            'last_seen' as ErrorTrackingQuery['order'],
            { persist: true },
            {
                setOrder: (_, { order }) => order,
            },
        ],
    }),
])
