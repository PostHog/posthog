import { actions, kea, path, reducers } from 'kea'

import type { maxGlobalLogicType } from './maxGlobalLogicType'

export const maxGlobalLogic = kea<maxGlobalLogicType>([
    path(['scenes', 'max', 'maxGlobalLogic']),
    actions({
        acceptDataProcessing: (testOnlyOverride?: boolean) => ({ testOnlyOverride }),
    }),
    reducers({
        dataProcessingAccepted: [
            false,
            { persist: true },
            {
                acceptDataProcessing: (_, { testOnlyOverride }) => testOnlyOverride ?? true,
            },
        ],
    }),
])
