import { DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger } from '@posthog/quill'

import { DisplayOptionTab } from 'lib/components/ChartOptions/displayOptions'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { DashboardInsightDisplayOptionsContent } from './DashboardInsightDisplayOptionsContent'

export function QuillDashboardInsightDisplayOptions({
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
            <DropdownMenuSeparator />
            <DropdownMenuSub>
                <DropdownMenuSubTrigger>Display options</DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                    <DashboardInsightDisplayOptionsContent visualizationItems={visualizationItems} tabs={tabs} />
                </DropdownMenuSubContent>
            </DropdownMenuSub>
        </>
    )
}
