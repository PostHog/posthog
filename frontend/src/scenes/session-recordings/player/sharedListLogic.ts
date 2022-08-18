import { kea, reducers, path, actions } from 'kea'
import type { sharedListLogicType } from './sharedListLogicType'
import { PlayerPosition, RecordingWindowFilter } from '~/types'

export type WindowOption = RecordingWindowFilter.All | PlayerPosition['windowId']

export const sharedListLogic = kea<sharedListLogicType>([
    path(['scenes', 'session-recordings', 'player', 'sharedListLogic']),
    actions(() => ({
        setWindowIdFilter: (windowId: WindowOption) => ({ windowId }),
        setOnlyMatchingEvents: (onlyMatchingEvents: boolean) => ({ onlyMatchingEvents }),
    })),
    reducers(() => ({
        windowIdFilter: [
            RecordingWindowFilter.All as WindowOption,
            {
                setWindowIdFilter: (_, { windowId }) => windowId ?? RecordingWindowFilter.All,
            },
        ],
        onlyMatchingEvents: [
            false,
            {
                setOnlyMatchingEvents: (_, { onlyMatchingEvents }) => !!onlyMatchingEvents ?? false,
            },
        ],
    })),
])
