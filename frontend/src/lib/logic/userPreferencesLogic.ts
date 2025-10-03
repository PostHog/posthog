import { actions, kea, path, reducers } from 'kea'

import type { userPreferencesLogicType } from './userPreferencesLogicType'

// This logic is for browser stored user preferences where it's not super important that it is persisted to the server
export const userPreferencesLogic = kea<userPreferencesLogicType>([
    path(['lib', 'logic', 'userPreferencesLogic']),
    actions({
        setHidePostHogPropertiesInTable: (enabled: boolean) => ({ enabled }),
        setHideNullValues: (enabled: boolean) => ({ enabled }),
        pinPersonProperty: (prop: string) => ({ prop }),
        unpinPersonProperty: (prop: string) => ({ prop }),
    }),
    reducers(() => ({
        hidePostHogPropertiesInTable: [
            false,
            { persist: true },
            {
                setHidePostHogPropertiesInTable: (_, { enabled }) => enabled,
            },
        ],
        hideNullValues: [true, { persist: true }, { setHideNullValues: (_, { enabled }) => enabled }],
        pinnedPersonProperties: [
            [] as string[],
            { persist: true },
            {
                pinPersonProperty: (state, { prop }) => (state.includes(prop) ? state : [...state, prop]),
                unpinPersonProperty: (state, { prop }) => state.filter((p) => p !== prop),
            },
        ],
    })),
])
