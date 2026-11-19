import { useValues } from 'kea'

import { dashboardV2Logic } from './dashboardV2Logic'
import { DashboardV2PanelGrid } from './DashboardV2PanelGrid'
import { DashboardV2RowSection } from './DashboardV2RowSection'
import { DashboardV2TabsSection } from './DashboardV2TabsSection'

export function DashboardV2Sections(): JSX.Element | null {
    const { sections, spec } = useValues(dashboardV2Logic)

    if (!spec) {
        return null
    }
    return (
        <div className="@container/dashboard-v2 flex flex-col gap-4" data-attr="dashboard-v2-sections">
            {sections.map((section) =>
                section.kind === 'grid' ? (
                    <DashboardV2PanelGrid key={section.key} items={section.items} panels={spec.panels} />
                ) : section.kind === 'row' ? (
                    <DashboardV2RowSection
                        key={section.key}
                        title={section.title}
                        collapsed={section.collapsed}
                        items={section.items}
                        panels={spec.panels}
                    />
                ) : (
                    <DashboardV2TabsSection key={section.key} tabs={section.tabs} panels={spec.panels} />
                )
            )}
        </div>
    )
}
