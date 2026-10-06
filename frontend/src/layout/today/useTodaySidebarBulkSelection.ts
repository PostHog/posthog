import { useActions, useValues } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { TodayBulkSelection } from './TodaySessionBulkActionItems'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { ownedBy } from './todayWorkItems'

export function useTodaySidebarBulkSelection(): TodayBulkSelection {
    const { selectedSessionIds, bulkPinDirection, bulkAction, runningSelectedCount, selectedSessions } =
        useValues(todaySessionSelectionLogic)
    const { user } = useValues(userLogic)
    const { pinSelected, fileSelectedTo, requestBulkArchive } = useActions(todaySessionSelectionLogic)
    return {
        spaceId: null,
        selectedSessionIds,
        ownsAllSelected: selectedSessions.every((item) => ownedBy(item, user?.id)),
        bulkPinDirection,
        bulkAction,
        runningSelectedCount,
        pinSelected,
        fileSelectedTo,
        requestBulkArchive,
    }
}
