import { kea, reducers, path, actions, props, key } from 'kea'
import type { sharedListLogicType } from './sharedListLogicType'
import { PlayerPosition, RecordingWindowFilter, SessionRecordingPlayerProps } from '~/types'

export type WindowOption = RecordingWindowFilter.All | PlayerPosition['windowId']

export const sharedListLogic = kea<sharedListLogicType>([
    path(['scenes', 'session-recordings', 'player', 'sharedListLogic']),
    props({} as SessionRecordingPlayerProps),
    key((props: SessionRecordingPlayerProps) => `${props.playerKey}-${props.sessionRecordingId}`),
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
