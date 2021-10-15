import { kea } from 'kea'
import { sessionRecordingPlayerLogicType } from './sessionRecordingPlayerLogicType'

export const sessionRecordingPlayerLogic = kea<sessionRecordingPlayerLogicType>({
    reducers: {
        test: [null, {}],
    },
})
