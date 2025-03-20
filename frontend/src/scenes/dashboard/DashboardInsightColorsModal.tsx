import { useActions, useValues } from 'kea'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { dashboardInsightColorsModalLogic } from './dashboardInsightColorsModalLogic'

export function DashboardInsightColorsModal(): JSX.Element {
    const { isOpen, breakdownValues } = useValues(dashboardInsightColorsModalLogic)
    const { hideInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)
    return (
        <LemonModal title="Customize Colors" isOpen={isOpen} onClose={hideInsightColorsModal}>
            {breakdownValues.map((value) => (
                <div key={value}>{value}</div>
            ))}
        </LemonModal>
    )
}
