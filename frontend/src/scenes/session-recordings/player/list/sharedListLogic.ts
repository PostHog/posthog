import { actions, kea, reducers, path } from 'kea'
import { PlayerPosition, RecordingWindowFilter } from '~/types'
import type { sharedListLogicType } from './sharedListLogicType'

export type WindowOption = RecordingWindowFilter.All | PlayerPosition['windowId']

export const sharedListLogic = kea<sharedListLogicType>([
    path(['scenes', 'session-recordings', 'player', 'sharedListLogic']),
    actions(() => ({
        setWindowIdFilter: (windowId: WindowOption) => ({ windowId }),
    })),
    reducers(() => ({
        windowIdFilter: [
            RecordingWindowFilter.All as WindowOption,
            {
                setWindowIdFilter: (_, { windowId }) => windowId ?? RecordingWindowFilter.All,
            },
        ],
    })),
])
