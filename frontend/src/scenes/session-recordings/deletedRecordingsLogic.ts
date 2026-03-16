import { actions, kea, path, reducers } from 'kea'

import type { deletedRecordingsLogicType } from './deletedRecordingsLogicType'

export const deletedRecordingsLogic = kea<deletedRecordingsLogicType>([
    path(['scenes', 'session-recordings', 'deletedRecordingsLogic']),
    actions({
        addDeletedRecordings: (ids: string[]) => ({ ids }),
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
    }),
])
