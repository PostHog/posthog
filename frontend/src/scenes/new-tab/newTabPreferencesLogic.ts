import { actions, kea, path, reducers } from 'kea'

import type { newTabPreferencesLogicType } from './newTabPreferencesLogicType'

export const newTabPreferencesLogic = kea<newTabPreferencesLogicType>([
    path(['scenes', 'new-tab', 'newTabPreferencesLogic']),
    actions({
        setAiFirstSearchEnabled: (enabled: boolean) => ({ enabled }),
    }),
    reducers({
        aiFirstSearchEnabled: [
            true, // defaults ON
            { persist: true },
            {
                setAiFirstSearchEnabled: (_, { enabled }: { enabled: boolean }) => enabled,
            },
        ],
    }),
])
