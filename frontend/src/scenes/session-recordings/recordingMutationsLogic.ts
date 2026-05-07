import { actions, kea, path, reducers } from 'kea'

import type { recordingMutationsLogicType } from './recordingMutationsLogicType'

// Shared singleton for recording mutations that need to sync between the player and playlist logics.
export const recordingMutationsLogic = kea<recordingMutationsLogicType>([
    path(['scenes', 'session-recordings', 'recordingMutationsLogic']),
    actions({
        addDeletedRecordings: (ids: string[]) => ({ ids }),
        recordingRenamed: (id: string, name: string | null) => ({ id, name }),
    }),
    reducers({
        deletedRecordingIds: [
            new Set<string>(),
            {
                addDeletedRecordings: (state, { ids }) => {
                    const next = new Set(state)
                    for (const id of ids) {
                        next.add(id)
                    }
                    return next
                },
            },
        ],
        renamedRecordings: [
            {} as Record<string, string | null>,
            {
                recordingRenamed: (state, { id, name }) => ({ ...state, [id]: name }),
            },
        ],
    }),
])
