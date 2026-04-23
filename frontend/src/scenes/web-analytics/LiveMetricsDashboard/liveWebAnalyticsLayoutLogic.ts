import { actions, kea, path, reducers, selectors } from 'kea'

import { DEFAULT_CONTENT_ORDER, DEFAULT_STAT_ORDER, LiveContentCardId, LiveStatCardId, mergeOrder } from './liveCards'
import type { liveWebAnalyticsLayoutLogicType } from './liveWebAnalyticsLayoutLogicType'

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }

export const liveWebAnalyticsLayoutLogic = kea<liveWebAnalyticsLayoutLogicType>([
    path(['scenes', 'webAnalytics', 'liveWebAnalyticsLayoutLogic']),
    actions({
        setStatOrder: (order: LiveStatCardId[]) => ({ order }),
        setCardOrder: (order: LiveContentCardId[]) => ({ order }),
        setEditing: (editing: boolean) => ({ editing }),
        resetLayout: true,
    }),
    reducers({
        persistedStatOrder: [
            [...DEFAULT_STAT_ORDER] as LiveStatCardId[],
            persistConfig,
            {
                setStatOrder: (_, { order }) => order,
                resetLayout: () => [...DEFAULT_STAT_ORDER],
            },
        ],
        persistedCardOrder: [
            [...DEFAULT_CONTENT_ORDER] as LiveContentCardId[],
            persistConfig,
            {
                setCardOrder: (_, { order }) => order,
                resetLayout: () => [...DEFAULT_CONTENT_ORDER],
            },
        ],
        isEditing: [
            false,
            {
                setEditing: (_, { editing }) => editing,
            },
        ],
    }),
    selectors({
        statOrder: [
            (s) => [s.persistedStatOrder],
            (persisted: LiveStatCardId[]): LiveStatCardId[] => mergeOrder(persisted, DEFAULT_STAT_ORDER),
        ],
        cardOrder: [
            (s) => [s.persistedCardOrder],
            (persisted: LiveContentCardId[]): LiveContentCardId[] => mergeOrder(persisted, DEFAULT_CONTENT_ORDER),
        ],
    }),
])
