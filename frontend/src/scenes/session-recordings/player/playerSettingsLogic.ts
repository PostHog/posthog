import { actions, kea, path, reducers } from 'kea'

import type { playerSettingsLogicType } from './playerSettingsLogicType'

// This logic contains player settings that should persist across players
// There is no key for this logic, so it does not reset when recordings change
export const playerSettingsLogic = kea<playerSettingsLogicType>([
    path(['scenes', 'session-recordings', 'player', 'playerSettingsLogic']),
    actions({
        setSkipInactivitySetting: (skipInactivitySetting: boolean) => ({ skipInactivitySetting }),
        setSpeed: (speed: number) => ({ speed }),
        setShowOnlyMatching: (showOnlyMatching: boolean) => ({ showOnlyMatching }),
    }),
    reducers({
        speed: [
            1,
            { persist: true },
            {
                setSpeed: (_, { speed }) => speed,
            },
        ],
        skipInactivitySetting: [
            true,
            { persist: true },
            {
                setSkipInactivitySetting: (_, { skipInactivitySetting }) => skipInactivitySetting,
            },
        ],
        showOnlyMatching: [
            false,
            {
                setShowOnlyMatching: (_, { showOnlyMatching }) => showOnlyMatching,
            },
        ],
    }),
])
