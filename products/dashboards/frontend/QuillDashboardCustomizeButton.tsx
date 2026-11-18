import { IconGridMasonry } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { DashboardCustomizeMenu } from 'products/dashboards/frontend/components/DashboardCustomizeMenu/DashboardCustomizeMenu'

export function QuillDashboardCustomizeButton(): JSX.Element {
    return (
        <Popover>
            <PopoverTrigger render={<Button variant="outline" data-attr="dashboard-edit-layout-customize-dropdown" />}>
                <IconGridMasonry />
                Customize
            </PopoverTrigger>
            <PopoverContent align="end" className="w-auto p-0">
                <DashboardCustomizeMenu />
            </PopoverContent>
        </Popover>
    )
}
