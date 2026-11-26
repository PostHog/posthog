import { DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger } from '@posthog/quill'

import { DisplayOptionTab } from 'lib/components/ChartOptions/displayOptions'
import { closesIntoLemonPopover } from 'lib/components/QuillSurface/closesIntoLemonPopover'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { DashboardInsightDisplayOptions } from './DashboardInsightDisplayOptions'

export function QuillDashboardInsightDisplayOptionsMenu({
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
        <DropdownMenuSub
            onOpenChange={(open, details) => {
                if (closesIntoLemonPopover(open, details)) {
                    details.cancel()
                }
            }}
        >
            <DropdownMenuSubTrigger>Display options</DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
                <DashboardInsightDisplayOptions visualizationItems={visualizationItems} tabs={tabs} />
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
