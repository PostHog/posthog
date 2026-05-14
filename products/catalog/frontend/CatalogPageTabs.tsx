import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

export type CatalogPageTab = 'proposals' | 'list' | 'graph'

const TABS: LemonTab<CatalogPageTab>[] = [
    { key: 'proposals', label: 'Proposals', link: urls.catalog() },
    { key: 'list', label: 'List', link: urls.catalogList() },
    { key: 'graph', label: 'Graph', link: urls.catalogGraph() },
]

/** Tabs shared between /catalog (list view) and /catalog/graph (graph view). */
export function CatalogPageTabs({ activeTab }: { activeTab: CatalogPageTab }): JSX.Element {
    return <LemonTabs activeKey={activeTab} tabs={TABS} />
}
