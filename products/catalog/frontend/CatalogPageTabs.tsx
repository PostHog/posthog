import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

export type CatalogPageTab = 'list' | 'graph'

const TABS: LemonTab<CatalogPageTab>[] = [
    { key: 'list', label: 'List', link: urls.catalog() },
    { key: 'graph', label: 'Graph', link: urls.catalogGraph() },
]

/** Tabs shared between /catalog (list view) and /catalog/graph (graph view). */
export function CatalogPageTabs({ activeTab }: { activeTab: CatalogPageTab }): JSX.Element {
    return <LemonTabs activeKey={activeTab} tabs={TABS} />
}
