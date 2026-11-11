import { useValues } from 'kea'

import { TodayPreviewCardProvider } from './TodayPreviewCardProvider'
import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { todaySessionSelectionLogic } from './todaySessionSelectionLogic'
import { todayShellLogic } from './todayShellLogic'
import { TodaySpacesSidebar } from './TodaySpacesSidebar'

export function TodaySpacesPane(): JSX.Element {
    const { sessionDialogOpen } = useValues(todaySessionMenuLogic)
    const { bulkArchiveConfirm } = useValues(todaySessionSelectionLogic)
    const { phoneLayout } = useValues(todayShellLogic)

    return (
        <TodayPreviewCardProvider disabled={phoneLayout || sessionDialogOpen || bulkArchiveConfirm.open}>
            <TodaySpacesSidebar />
        </TodayPreviewCardProvider>
    )
}
