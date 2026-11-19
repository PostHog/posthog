import type { CSSProperties } from 'react'

import { useDisplay } from '../editor/display'
import type { DashboardV2PanelApi, DashboardV2PanelItemApi } from '../generated/api.schemas'
import { DashboardV2SamplePanel } from '../panel/DashboardV2SamplePanel'

interface DashboardV2PanelGridProps {
    items: DashboardV2PanelItemApi[]
    panels: Record<string, DashboardV2PanelApi>
}

// Stand-in for the real grid, with no drag or resize. Dense placement packs panels upward, as the document format expects.
export function DashboardV2PanelGrid({ items, panels }: DashboardV2PanelGridProps): JSX.Element {
    const spacious = useDisplay() === 'spacious'
    return (
        <div
            // 1.875rem is the 30px grid unit that panel heights in a document count in.
            className={`grid grid-flow-row-dense grid-cols-1 @min-[48rem]/dashboard-v2:grid-cols-24 ${spacious ? 'gap-5 @min-[48rem]/dashboard-v2:auto-rows-[2rem]' : 'gap-2 @min-[48rem]/dashboard-v2:auto-rows-[1.875rem]'}`}
        >
            {items.map((item) =>
                panels[item.panel] ? (
                    <div
                        key={item.panel}
                        className="min-w-0 @min-[48rem]/dashboard-v2:[grid-column:var(--panel-column)] @min-[48rem]/dashboard-v2:[grid-row:var(--panel-row)]"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={
                            {
                                '--panel-column': `${item.x + 1} / span ${item.w}`,
                                '--panel-row': `span ${item.h}`,
                            } as CSSProperties
                        }
                    >
                        <DashboardV2SamplePanel id={item.panel} panel={panels[item.panel]} />
                    </div>
                ) : null
            )}
        </div>
    )
}
