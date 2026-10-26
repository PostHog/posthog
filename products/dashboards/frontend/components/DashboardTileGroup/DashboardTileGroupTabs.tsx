import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { type DashboardSection, getTileGroupLabel } from '../../dashboardTileSections'
import { TileGroupColorDot } from './TileGroupColorDot'

interface DashboardTileGroupTabsProps {
    sections: DashboardSection[]
    activeSectionKey: string
    onSelect: (sectionKey: string) => void
    children: React.ReactNode
}

export function DashboardTileGroupTabs({
    sections,
    activeSectionKey,
    onSelect,
    children,
}: DashboardTileGroupTabsProps): JSX.Element {
    return (
        <section data-attr="dashboard-tile-group-tabs">
            <LemonTabs
                activeKey={activeSectionKey}
                onChange={onSelect}
                tabs={sections.map((section) => ({
                    key: section.key,
                    label:
                        section.kind === 'group' ? (
                            <span className="flex items-center gap-2">
                                {section.group.color && <TileGroupColorDot color={section.group.color} />}
                                {getTileGroupLabel(section.group, section.tiles.length)}
                            </span>
                        ) : (
                            'Other tiles'
                        ),
                }))}
            />
            {children}
        </section>
    )
}
