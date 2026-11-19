import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@posthog/quill'

import type { DashboardV2PanelApi, DashboardV2PanelItemApi } from '../generated/api.schemas'
import { DashboardV2PanelGrid } from './DashboardV2PanelGrid'

interface DashboardV2RowSectionProps {
    title: string
    collapsed: boolean
    items: DashboardV2PanelItemApi[]
    panels: Record<string, DashboardV2PanelApi>
}

export function DashboardV2RowSection({ title, collapsed, items, panels }: DashboardV2RowSectionProps): JSX.Element {
    return (
        <Collapsible defaultOpen={!collapsed} data-attr="dashboard-v2-row">
            <CollapsibleTrigger>{title}</CollapsibleTrigger>
            <CollapsibleContent className="pt-2">
                <DashboardV2PanelGrid items={items} panels={panels} />
            </CollapsibleContent>
        </Collapsible>
    )
}
