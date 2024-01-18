import { actions, kea, path, reducers } from 'kea'

import type { userPreferencesLogicType } from './userPreferencesLogicType'

// This logic contains player settings that should persist across players
// If key is not specified, it is global so it does not reset when recordings change in the main recordings page
export const userPreferencesLogic = kea<userPreferencesLogicType>([
    path(['lib', 'logic', 'userPreferencesLogic']),
    actions({
        setHidePostHogPropertiesInTable: (enabled: boolean) => ({ enabled }),
    }),
    reducers(() => ({
        hidePostHogPropertiesInTable: [
            false,
            { persist: true },
            {
                setHidePostHogPropertiesInTable: (_, { enabled }) => enabled,
            },
        ],
    })),
])
