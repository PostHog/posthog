import { actions, kea, path, reducers } from 'kea'

import type { homeViewToggleLogicType } from './homeViewToggleLogicType'

export const homeViewToggleLogic = kea<homeViewToggleLogicType>([
    path(['layout', 'scenes', 'homeViewToggleLogic']),
    actions({
        setExpanded: (expanded: boolean) => ({ expanded }),
    }),
    reducers({
        // Persisted so the picker stays open while hopping between the home views,
        // which remount the toggle on every scene change
        expanded: [
            false,
            { persist: true },
            {
                setExpanded: (_, { expanded }) => expanded,
            },
        ],
    }),
])
