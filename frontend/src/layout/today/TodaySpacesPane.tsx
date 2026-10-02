import { useValues } from 'kea'

import { TodayPreviewCardProvider } from './TodayPreviewCardProvider'
import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { TodaySpacesSidebar } from './TodaySpacesSidebar'

export function TodaySpacesPane(): JSX.Element {
    const { sessionDialogOpen } = useValues(todaySessionMenuLogic)
    const { bulkArchiveConfirm } = useValues(todaySessionSelectionLogic)

    return (
        <TodayPreviewCardProvider disabled={sessionDialogOpen || bulkArchiveConfirm.open}>
            <TodaySpacesSidebar />
        </TodayPreviewCardProvider>
    )
}
