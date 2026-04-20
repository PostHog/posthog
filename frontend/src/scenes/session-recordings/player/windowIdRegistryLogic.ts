import { actions, kea, key, path, props, reducers, selectors } from 'kea'

import { SessionRecordingId } from '~/types'

import type { windowIdRegistryLogicType } from './windowIdRegistryLogicType'

export interface WindowIdRegistryLogicProps {
    sessionRecordingId: SessionRecordingId
}

export const windowIdRegistryLogic = kea<windowIdRegistryLogicType>([
    path((key) => ['scenes', 'session-recordings', 'windowIdRegistryLogic', key]),
    props({} as WindowIdRegistryLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    actions({
        registerWindowId: (uuid: string) => ({ uuid }),
    }),
    reducers({
        uuidToIndex: [
            {} as Record<string, number>,
            {
                registerWindowId: (state, { uuid }) => {
                    if (uuid in state) {
                        return state
                    }
                    return { ...state, [uuid]: Object.keys(state).length + 1 }
                },
            },
        ],
    }),
    selectors({
        getWindowId: [
            (s) => [s.uuidToIndex],
            (uuidToIndex) =>
                (uuid: string | undefined): number | undefined => {
                    if (!uuid) {
                        return undefined
                    }
                    return uuidToIndex[uuid]
                },
        ],
        windowIds: [
            (s) => [s.uuidToIndex],
            (uuidToIndex): number[] => Object.values(uuidToIndex).sort((a, b) => a - b),
        ],
    }),
])
