import { Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import type { DashboardV2PanelApi, DashboardV2PanelItemApi } from '../generated/api.schemas'
import { DashboardV2PanelGrid } from './DashboardV2PanelGrid'

interface DashboardV2TabsSectionProps {
    tabs: { title: string; items: DashboardV2PanelItemApi[] }[]
    panels: Record<string, DashboardV2PanelApi>
}

export function DashboardV2TabsSection({ tabs, panels }: DashboardV2TabsSectionProps): JSX.Element {
    return (
        <Tabs defaultValue="0" data-attr="dashboard-v2-tabs">
            <TabsList variant="line">
                {tabs.map((tab, index) => (
                    <TabsTrigger key={index} value={String(index)}>
                        {tab.title}
                    </TabsTrigger>
                ))}
            </TabsList>
            {tabs.map((tab, index) => (
                <TabsContent key={index} value={String(index)} className="pt-2">
                    <DashboardV2PanelGrid items={tab.items} panels={panels} />
                </TabsContent>
            ))}
        </Tabs>
    )
}
