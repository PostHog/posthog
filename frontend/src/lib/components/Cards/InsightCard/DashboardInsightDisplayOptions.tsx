import { IconChevronRight } from '@posthog/icons'

import { DisplayOptionTab } from 'lib/components/ChartOptions/displayOptions'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { DashboardInsightDisplayOptionsContent } from './DashboardInsightDisplayOptionsContent'

// Items are computed in InsightMeta (always mounted) and passed down to avoid mounting
// useDisplayOptions(insightDisplayOptions) lazily inside the More popover overlay, which triggers kea logic
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
                overlay={<DashboardInsightDisplayOptionsContent visualizationItems={visualizationItems} tabs={tabs} />}
                closeOnClickInside={false}
                placement="right-start"
                fallbackPlacements={['left-start']}
            >
                <LemonButton fullWidth sideIcon={<IconChevronRight className="size-3" />}>
                    Display options
                </LemonButton>
            </LemonDropdown>
        </>
    )
}
