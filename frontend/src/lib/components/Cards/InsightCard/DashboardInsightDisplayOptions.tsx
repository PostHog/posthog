import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { LemonMenuItems, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'

import { DisplayOptionTab } from '~/queries/nodes/InsightViz/insightDisplayOptions'
import { InsightDisplayOptionsPanel } from '~/queries/nodes/InsightViz/InsightDisplayOptionsPanel'

// Items are computed in InsightMeta (always mounted) and passed down to avoid mounting
// useInsightDisplayOptions lazily inside the More popover overlay, which triggers kea logic
// mounts that cascade and close the popover before the user can interact with it.
export function DashboardInsightDisplayOptions({
    visualizationItems,
    tabs,
}: {
    visualizationItems: LemonMenuItems
    tabs: DisplayOptionTab[]
}): JSX.Element | null {
    if (visualizationItems.length === 0 && tabs.length === 0) {
        return null
    }

    return (
        <>
            <LemonDivider />
            <LemonDropdown
                overlay={
                    <>
                        {visualizationItems.length > 0 && <LemonMenuOverlay items={visualizationItems} />}
                        {visualizationItems.length > 0 && tabs.length > 0 && <LemonDivider />}
                        <InsightDisplayOptionsPanel tabs={tabs} />
                    </>
                }
                closeOnClickInside={false}
                placement="right-start"
                fallbackPlacements={['left-start']}
            >
                <LemonButton fullWidth>Display options</LemonButton>
            </LemonDropdown>
        </>
    )
}
