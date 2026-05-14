import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

export type CatalogPageTab = 'entities' | 'list' | 'graph'

const TABS: LemonTab<CatalogPageTab>[] = [
    { key: 'entities', label: 'Entities', link: urls.catalog() },
    { key: 'list', label: 'Tables', link: urls.catalogList() },
    { key: 'graph', label: 'Graph', link: urls.catalogGraph() },
]

/** Tabs shared between the catalog browser, table list, and graph view. */
export function CatalogPageTabs({ activeTab }: { activeTab: CatalogPageTab }): JSX.Element {
    return <LemonTabs activeKey={activeTab} tabs={TABS} />
}
