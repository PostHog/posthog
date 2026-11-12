import { DisplayOptionTab } from 'lib/components/ChartOptions/displayOptions'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenuItems, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'

import { InsightDisplayOptionsPanel } from 'products/product_analytics/frontend/insights/editor/InsightDisplayOptionsPanel'

export function DashboardInsightDisplayOptionsContent({
    visualizationItems,
    tabs,
}: {
    visualizationItems: LemonMenuItems
    tabs: DisplayOptionTab[]
}): JSX.Element {
    return (
        <>
            {visualizationItems.length > 0 && <LemonMenuOverlay items={visualizationItems} />}
            {visualizationItems.length > 0 && tabs.length > 0 && <LemonDivider />}
            <InsightDisplayOptionsPanel tabs={tabs} />
        </>
    )
}
