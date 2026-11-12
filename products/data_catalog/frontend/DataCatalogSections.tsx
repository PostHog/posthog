import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { QuillModelsLineageTab } from 'products/data_modeling/frontend/lineage/QuillModelsLineageTab'

import { CatalogOverview } from './CatalogOverview'
import { CatalogUsageSection } from './CatalogUsageSection'
import { dataCatalogAttentionLogic } from './dataCatalogAttentionLogic'
import { DataCatalogTab, dataCatalogSceneLogic } from './dataCatalogSceneLogic'
import { CatalogDataQualitySection } from './dataQuality/CatalogDataQualitySection'
import { CatalogMetricsSection } from './metrics/CatalogMetricsSection'
import { CatalogRelationshipsSection } from './relationships/CatalogRelationshipsSection'
import { CatalogTablesSection } from './tables/CatalogTablesSection'
import { WarehouseAccessGate } from './WarehouseAccessGate'

const VISIBLE_SECTIONS: DataCatalogTab[] = ['overview', 'tables', 'lineage', 'metrics']

const OVERFLOW_BREAKPOINTS: { showTab: string; hideMoreButton: string }[] = [
    { showTab: 'hidden @lg:flex', hideMoreButton: '@lg:hidden' },
    { showTab: 'hidden @xl:flex', hideMoreButton: '@xl:hidden' },
    { showTab: 'hidden @2xl:flex', hideMoreButton: '@2xl:hidden' },
]

const SECTION_LABELS: Record<DataCatalogTab, string> = {
    overview: 'Overview',
    tables: 'Tables & views',
    lineage: 'Lineage',
    metrics: 'Metrics',
    relationships: 'Relationships',
    'data-quality': 'Data quality',
    certifications: 'Certifications',
    usage: 'Usage',
}

const WAREHOUSE_SECTIONS: DataCatalogTab[] = ['tables', 'lineage', 'data-quality', 'usage']

const FAILURE_SECTIONS: DataCatalogTab[] = ['overview', 'data-quality']

const SECTION_CONTENT: Partial<Record<DataCatalogTab, () => JSX.Element>> = {
    overview: CatalogOverview,
    tables: CatalogTablesSection,
    lineage: QuillModelsLineageTab,
    metrics: CatalogMetricsSection,
    relationships: CatalogRelationshipsSection,
    'data-quality': CatalogDataQualitySection,
    usage: CatalogUsageSection,
}

function SectionCount({ tab, count }: { tab: DataCatalogTab; count: number | undefined }): JSX.Element | null {
    if (!count) {
        return null
    }
    return <Badge variant={FAILURE_SECTIONS.includes(tab) ? 'destructive' : 'default'}>{count}</Badge>
}

function SceneActions(): JSX.Element {
    return (
        <div className="flex flex-wrap gap-2">
            <Button
                variant="outline"
                render={<LinkPrimitive to={urls.dataCatalogNewMetric()} />}
                data-attr="data-catalog-new-metric-button"
            >
                New metric
            </Button>
            <AccessControlAction
                resourceType={AccessControlResourceType.WarehouseObjects}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <Button
                    variant="primary"
                    render={<LinkPrimitive to={urls.sqlEditor({ source: 'view' })} />}
                    data-attr="data-catalog-create-view-button"
                >
                    <IconPlus />
                    Create view
                </Button>
            </AccessControlAction>
        </div>
    )
}

export function DataCatalogSections(): JSX.Element {
    const { activeTab, availableTabs, defaultTab, lineageVisited } = useValues(dataCatalogSceneLogic)
    const { tabCounts } = useValues(dataCatalogAttentionLogic)
    const moreSections = availableTabs.filter((tab) => !VISIBLE_SECTIONS.includes(tab))
    const inactiveMoreSections = moreSections.filter((tab) => tab !== activeTab)
    const lastInactiveMoreIndex = moreSections.findLastIndex((tab) => tab !== activeTab)

    const openSection = (tab: DataCatalogTab): void => {
        router.actions.push(urls.dataCatalog(tab === defaultTab ? undefined : tab))
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Data catalog"
                description="Check the health of your tables and views, see how they connect, and manage metrics."
                resourceType={{ type: 'data_warehouse' }}
                actions={<SceneActions />}
            />
            <Tabs value={activeTab} onValueChange={(tab: DataCatalogTab) => openSection(tab)} data-quill>
                <div className="@container flex flex-wrap items-center gap-2 border-b border-border">
                    <TabsList variant="line" aria-label="Data catalog sections">
                        {VISIBLE_SECTIONS.map((tab) => (
                            <TabsTrigger key={tab} value={tab} data-attr={`data-catalog-section-${tab}`}>
                                {SECTION_LABELS[tab]}
                                <SectionCount tab={tab} count={tabCounts[tab]} />
                            </TabsTrigger>
                        ))}
                        {moreSections.map((tab, index) => (
                            <TabsTrigger
                                key={tab}
                                value={tab}
                                className={tab === activeTab ? undefined : OVERFLOW_BREAKPOINTS[index]?.showTab}
                                data-attr={`data-catalog-section-${tab}`}
                            >
                                {SECTION_LABELS[tab]}
                                <SectionCount tab={tab} count={tabCounts[tab]} />
                            </TabsTrigger>
                        ))}
                    </TabsList>
                    {lastInactiveMoreIndex >= 0 && (
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={
                                    <Button
                                        variant="default"
                                        size="sm"
                                        className={OVERFLOW_BREAKPOINTS[lastInactiveMoreIndex]?.hideMoreButton}
                                        data-attr="data-catalog-section-more"
                                    />
                                }
                            >
                                More
                                <IconChevronDown />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="start">
                                {inactiveMoreSections.map((tab) => (
                                    <DropdownMenuItem
                                        key={tab}
                                        onClick={() => openSection(tab)}
                                        data-attr={`data-catalog-section-${tab}`}
                                    >
                                        {SECTION_LABELS[tab]}
                                        <SectionCount tab={tab} count={tabCounts[tab]} />
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )}
                </div>
                {availableTabs.map((tab) => {
                    const Content = SECTION_CONTENT[tab]
                    if (!Content) {
                        return null
                    }
                    const keepMounted = tab === 'lineage' && lineageVisited
                    return (
                        <TabsContent key={tab} value={tab} keepMounted={keepMounted} className="pt-4 pb-8">
                            {(tab === activeTab || keepMounted) &&
                                (WAREHOUSE_SECTIONS.includes(tab) ? (
                                    <WarehouseAccessGate>
                                        <Content />
                                    </WarehouseAccessGate>
                                ) : (
                                    <Content />
                                ))}
                        </TabsContent>
                    )
                })}
            </Tabs>
        </SceneContent>
    )
}
