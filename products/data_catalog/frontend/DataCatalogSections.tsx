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

import { ModelsLineageTab } from 'products/data_modeling/frontend/lineage/ModelsLineageTab'

import { CatalogOverview } from './CatalogOverview'
import { CatalogUsageSection } from './CatalogUsageSection'
import { DataCatalogTab, dataCatalogSceneLogic } from './dataCatalogSceneLogic'
import { CatalogDataQualitySection } from './dataQuality/CatalogDataQualitySection'
import { relationshipsLogic } from './relationshipsLogic'
import { CatalogTablesSection } from './tables/CatalogTablesSection'
import { MetricsTab } from './tabs/MetricsTab'
import { RelationshipsTab } from './tabs/RelationshipsTab'
import { WarehouseAccessGate } from './WarehouseAccessGate'

const VISIBLE_SECTIONS: DataCatalogTab[] = ['overview', 'tables', 'lineage', 'metrics']

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

const SECTION_CONTENT: Partial<Record<DataCatalogTab, () => JSX.Element>> = {
    overview: CatalogOverview,
    tables: CatalogTablesSection,
    lineage: ModelsLineageTab,
    metrics: MetricsTab,
    relationships: RelationshipsTab,
    'data-quality': CatalogDataQualitySection,
    usage: CatalogUsageSection,
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
    const { pendingCount: proposedJoins } = useValues(relationshipsLogic)
    const moreSections = availableTabs.filter((tab) => !VISIBLE_SECTIONS.includes(tab))
    const activeMoreSection = moreSections.includes(activeTab) ? activeTab : null

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
                <div className="flex flex-wrap items-center gap-2 border-b border-border">
                    <TabsList variant="line" aria-label="Data catalog sections">
                        {VISIBLE_SECTIONS.map((tab) => (
                            <TabsTrigger key={tab} value={tab} data-attr={`data-catalog-section-${tab}`}>
                                {SECTION_LABELS[tab]}
                            </TabsTrigger>
                        ))}
                        {activeMoreSection && (
                            <TabsTrigger value={activeMoreSection}>{SECTION_LABELS[activeMoreSection]}</TabsTrigger>
                        )}
                    </TabsList>
                    {moreSections.length > 0 && (
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={<Button variant="default" size="sm" data-attr="data-catalog-section-more" />}
                            >
                                More
                                <IconChevronDown />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="start">
                                {moreSections.map((tab) => (
                                    <DropdownMenuItem
                                        key={tab}
                                        onClick={() => openSection(tab)}
                                        data-attr={`data-catalog-section-${tab}`}
                                    >
                                        {SECTION_LABELS[tab]}
                                        {tab === 'relationships' && proposedJoins > 0 && <Badge>{proposedJoins}</Badge>}
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
