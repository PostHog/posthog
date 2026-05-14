import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

export type CatalogPageTab = 'proposals' | 'list' | 'graph' | 'logs'

const TABS: LemonTab<CatalogPageTab>[] = [
    { key: 'proposals', label: 'Inbox', link: urls.catalog() },
    { key: 'list', label: 'Nodes', link: urls.catalogList() },
    { key: 'graph', label: 'Lineage', link: urls.catalogGraph() },
    { key: 'logs', label: 'Logs', link: urls.catalogLogs() },
]

/** Tabs shared between /catalog (list view) and /catalog/graph (graph view). */
export function CatalogPageTabs({ activeTab }: { activeTab: CatalogPageTab }): JSX.Element {
    return <LemonTabs activeKey={activeTab} tabs={TABS} />
}
