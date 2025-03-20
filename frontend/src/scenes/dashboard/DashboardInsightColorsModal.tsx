import { useActions, useValues } from 'kea'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { dashboardInsightColorsModalLogic } from './dashboardInsightColorsModalLogic'

export function DashboardInsightColorsModal(): JSX.Element {
    const { isOpen } = useValues(dashboardInsightColorsModalLogic)
    const { hideInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)
    return (
        <LemonModal title="Customize Colors" isOpen={isOpen} onClose={hideInsightColorsModal}>
            {/* Content will be added in future implementations */}
        </LemonModal>
    )
}
