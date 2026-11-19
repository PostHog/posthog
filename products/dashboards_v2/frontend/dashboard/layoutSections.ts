import type { DashboardV2LayoutApi, DashboardV2PanelItemApi } from '../generated/api.schemas'

export type DashboardV2Section =
    | { kind: 'grid'; key: string; items: DashboardV2PanelItemApi[] }
    | { kind: 'row'; key: string; title: string; collapsed: boolean; items: DashboardV2PanelItemApi[] }
    | { kind: 'tabs'; key: string; tabs: { title: string; items: DashboardV2PanelItemApi[] }[] }

type LayoutItem = DashboardV2LayoutApi['items'][number]

function byPosition(a: DashboardV2PanelItemApi, b: DashboardV2PanelItemApi): number {
    return a.y - b.y || a.x - b.x
}

// A run of panels between two rows or tab groups is one section, because each section is its own 24-column grid.
export function layoutSections(layout: DashboardV2LayoutApi): DashboardV2Section[] {
    const sections: DashboardV2Section[] = []
    const ordered = layout.items.map((item, index) => ({ item, index })).sort((a, b) => a.item.y - b.item.y)
    let grids = 0

    for (const { item, index } of ordered as { item: LayoutItem; index: number }[]) {
        if ('panel' in item) {
            const last = sections[sections.length - 1]
            if (last?.kind === 'grid') {
                last.items.push(item)
            } else {
                sections.push({ kind: 'grid', key: `grid-${grids++}`, items: [item] })
            }
        } else if ('row' in item) {
            sections.push({
                kind: 'row',
                key: `row-${index}`,
                title: item.row,
                collapsed: !!item.collapsed,
                items: [...item.items].sort(byPosition),
            })
        } else {
            sections.push({
                kind: 'tabs',
                key: `tabs-${index}`,
                tabs: item.items.map((tab) => ({ title: tab.title, items: [...tab.items].sort(byPosition) })),
            })
        }
    }

    for (const section of sections) {
        if (section.kind === 'grid') {
            section.items.sort(byPosition)
        }
    }
    return sections
}
