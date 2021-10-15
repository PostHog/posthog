import { kea } from 'kea'
import { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'
import { Replayer } from 'rrweb'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { sessionsPlayLogic } from 'scenes/sessions/sessionsPlayLogic'

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType>({
    connect: {
        logic: [eventUsageLogic],
        values: [sessionsPlayLogic, ['sessionRecordingId', 'sessionPlayerData']],
        actions: [
            sessionsTableLogic,
            ['fetchNextSessions', 'appendNewSessions', 'closeSessionPlayer', 'loadSessionEvents'],
        ],
    },
    actions: {
        setReplayer: (replayer: Replayer) => ({ replayer }),
    },
    reducers: {
        replayer: [
            null as Replayer | null,
            {
                setReplayer: (_, { replayer }) => replayer,
            },
        ],
    },
})
