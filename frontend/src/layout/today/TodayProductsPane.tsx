import { useValues } from 'kea'

import { TodayPreviewCardProvider } from './TodayPreviewCardProvider'
import { TodayProductsSidebar } from './TodayProductsSidebar'
import { todayShellLogic } from './todayShellLogic'

export function TodayProductsPane(): JSX.Element {
    const { phoneLayout } = useValues(todayShellLogic)

    return (
        <TodayPreviewCardProvider disabled={phoneLayout}>
            <TodayProductsSidebar />
        </TodayPreviewCardProvider>
    )
}
