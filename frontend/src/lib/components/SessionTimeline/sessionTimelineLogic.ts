import { actions, defaults, kea, key, path, props, reducers, selectors } from 'kea'

import { Dayjs, dayjs } from 'lib/dayjs'

import type { sessionTimelineLogicType } from './sessionTimelineLogicType'
import { ItemCategory, ItemCollector, TimelineItem } from './timeline'

export type SessionTabLogicProps = {
    sessionId: string
    timestamp: string
}

export type TabId = 'recording' | 'timeline'

export type TimelineEvent = {
    uuid: string
    event: string
    timestamp: string
}

export const sessionTimelineLogic = kea<sessionTimelineLogicType>([
    path((key) => ['components', 'sessionTimeline', key]),
    props({} as SessionTabLogicProps),
    key(({ sessionId }) => sessionId as KeyType),

    actions({
        toggleCategory: (category: ItemCategory) => ({ category }),
        setItems: (items: TimelineItem[]) => ({ items }),
    }),

    defaults({
        currentCategories: [
            ItemCategory.ERROR_TRACKING,
            ItemCategory.PAGE_VIEWS,
            ItemCategory.CUSTOM_EVENTS,
        ] as ItemCategory[],
        recordingTimestamp: null as number | null,
        items: [] as TimelineItem[],
        collector: null as ItemCollector | null,
    }),

    reducers({
        currentCategories: {
            toggleCategory: (state, { category }: { category: ItemCategory }) => {
                if (state.includes(category)) {
                    return state.filter((c) => c !== category)
                }
                return [...state, category]
            },
        },
        recordingTimestamp: {
            setRecordingTimestamp: (_, { timestamp, offset }: { timestamp: Dayjs; offset: number }) =>
                dayjs(timestamp).valueOf() - offset,
        },
        items: {
            setItems: (_, { items }: { items: TimelineItem[] }) => items,
        },
        collector: {
            setCollector: (_, { collector }: { collector: ItemCollector }) => collector,
        },
    }),
    selectors({
        sessionId: [(_, p) => [p.sessionId], (sessionId) => sessionId],
        timestamp: [(_, p) => [p.timestamp], (timestamp) => timestamp],
    }),
])
