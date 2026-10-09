import { useActions, useValues } from 'kea'

import { TodayBulkSelection } from './TodaySessionBulkActionItems'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'

export function useTodaySidebarBulkSelection(): TodayBulkSelection {
    const { selectedSessionIds, bulkPinDirection, bulkAction, runningSelectedCount } =
        useValues(todaySessionSelectionLogic)
    const { pinSelected, requestBulkArchive } = useActions(todaySessionSelectionLogic)
    return {
        selectedSessionIds,
        bulkPinDirection,
        bulkAction,
        runningSelectedCount,
        pinSelected,
        requestBulkArchive,
    }
}
