import { actions, kea, path, reducers } from 'kea'

import type { livePersonDrillDownDrawerLogicType } from './livePersonDrillDownDrawerLogicType'

export type LivePersonDrillDownBreakdownType = 'country' | 'city' | 'device' | 'browser'

export interface LivePersonDrillDownSelection {
    breakdownType: LivePersonDrillDownBreakdownType
    breakdownValue: string
    breakdownLabel: string
}

export const livePersonDrillDownDrawerLogic = kea<livePersonDrillDownDrawerLogicType>([
    path(['scenes', 'webAnalytics', 'livePersonDrillDownDrawerLogic']),
    actions({
        openDrillDown: (selection: LivePersonDrillDownSelection) => selection,
        closeDrillDown: true,
    }),
    reducers({
        currentSelection: [
            null as LivePersonDrillDownSelection | null,
            {
                openDrillDown: (_, payload) => payload,
                closeDrillDown: () => null,
            },
        ],
    }),
])
