import { useActions, useValues } from 'kea'

import { IconAIText, IconCheck, IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type {
    CatalogDimensionDTOApi,
    CatalogEntityDTOApi,
    CatalogMetricDTOApi,
} from 'products/catalog/frontend/generated/api.schemas'

import { catalogBrowserSceneLogic } from './catalogBrowserSceneLogic'
import { STATUS_COLOR, STATUS_LABEL } from './catalogConstants'
import { CatalogPageTabs } from './CatalogPageTabs'

export const scene: SceneExport = {
    component: CatalogBrowserScene,
    logic: catalogBrowserSceneLogic,
    productKey: ProductKey.CATALOG,
}

export function CatalogBrowserScene(): JSX.Element {
    const { browser, browserLoading, entities, selectedEntity } = useValues(catalogBrowserSceneLogic)
    const { setSelectedEntityId, deriveCatalog, clusterCatalog } = useActions(catalogBrowserSceneLogic)

    if (browserLoading && !browser) {
        return (
            <SceneContent>
                <LemonSkeleton className="h-8 w-64" />
                <LemonSkeleton className="h-64 w-full" />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Catalog"
                description="Business objects, metrics, and dimensions derived from your data."
                resourceType={{ type: 'data_warehouse' }}
                actions={
                    <>
                        <LemonButton type="secondary" icon={<IconSparkles />} onClick={deriveCatalog}>
                            Derive proposals
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            icon={<IconAIText />}
                            onClick={clusterCatalog}
                            tooltip="Run an LLM pass that merges the per-table entities into business objects like Customer, Order, Subscription."
                        >
                            Cluster with AI
                        </LemonButton>
                    </>
                }
            />
            <CatalogPageTabs activeTab="entities" />
            {entities.length === 0 ? (
                <EmptyState />
            ) : (
                <div className="grid grid-cols-[260px_1fr] gap-4 border rounded overflow-hidden">
                    <EntitySidebar
                        entities={entities}
                        selectedEntityId={selectedEntity?.id ?? null}
                        onSelect={setSelectedEntityId}
                    />
                    <div className="p-4 min-h-[400px]">
                        {selectedEntity ? (
                            <EntityDetail entity={selectedEntity} />
                        ) : (
                            <div className="text-secondary text-sm">Select an entity on the left.</div>
                        )}
                    </div>
                </div>
            )}
        </SceneContent>
    )
}

function EmptyState(): JSX.Element {
    const { deriveCatalog } = useActions(catalogBrowserSceneLogic)
    return (
        <div className="border rounded p-8 text-center">
            <h3 className="text-base font-semibold mb-1">No entities yet</h3>
            <p className="text-sm text-secondary mb-4">
                Run derivation to propose entities, metrics, and dimensions from your current catalog state.
            </p>
            <LemonButton type="primary" icon={<IconSparkles />} onClick={deriveCatalog}>
                Derive proposals
            </LemonButton>
        </div>
    )
}

function EntitySidebar({
    entities,
    selectedEntityId,
    onSelect,
}: {
    entities: CatalogEntityDTOApi[]
    selectedEntityId: string | null
    onSelect: (id: string) => void
}): JSX.Element {
    return (
        <div className="border-r bg-bg-3000/40 overflow-y-auto max-h-[700px]">
            {entities.map((entity) => {
                const isSelected = entity.id === selectedEntityId
                return (
                    <button
                        key={entity.id}
                        type="button"
                        onClick={() => onSelect(entity.id)}
                        className={`w-full text-left px-3 py-2 border-b text-sm flex items-center gap-2 cursor-pointer transition-colors ${
                            isSelected ? 'bg-surface-secondary font-semibold' : 'hover:bg-surface-secondary'
                        }`}
                    >
                        <span className="truncate flex-1">{entity.name}</span>
                        <LemonTag size="small" type={STATUS_COLOR[entity.status] ?? 'default'}>
                            {STATUS_LABEL[entity.status] ?? entity.status}
                        </LemonTag>
                    </button>
                )
            })}
        </div>
    )
}

function EntityDetail({ entity }: { entity: CatalogEntityDTOApi }): JSX.Element {
    const { metricsForSelectedEntity, dimensionsForSelectedEntity } = useValues(catalogBrowserSceneLogic)
    const { updateEntity } = useActions(catalogBrowserSceneLogic)

    return (
        <div className="flex flex-col gap-6">
            <div className="flex items-start gap-3">
                <div className="flex-1">
                    <div className="flex items-center gap-2">
                        <h2 className="text-xl font-semibold m-0">{entity.name}</h2>
                        <LemonTag type={STATUS_COLOR[entity.status] ?? 'default'}>
                            {STATUS_LABEL[entity.status] ?? entity.status}
                        </LemonTag>
                    </div>
                    <p className="text-sm text-secondary mt-1 mb-0">{entity.description ?? 'No description yet.'}</p>
                    <p className="text-xs text-secondary mt-2 mb-0">
                        {entity.member_node_ids.length} member node
                        {entity.member_node_ids.length === 1 ? '' : 's'}
                    </p>
                </div>
                {entity.status === 'proposed' && (
                    <ReviewButtons
                        onAccept={() => updateEntity(entity.id, { status: 'accepted' })}
                        onReject={() => updateEntity(entity.id, { status: 'rejected' })}
                    />
                )}
            </div>
            <Section label="Metrics" count={metricsForSelectedEntity.length}>
                {metricsForSelectedEntity.length === 0 ? (
                    <EmptyRow text="No metrics proposed for this entity yet." />
                ) : (
                    metricsForSelectedEntity.map((metric) => <MetricRow key={metric.id} metric={metric} />)
                )}
            </Section>
            <Section label="Dimensions" count={dimensionsForSelectedEntity.length}>
                {dimensionsForSelectedEntity.length === 0 ? (
                    <EmptyRow text="No dimensions proposed for this entity yet." />
                ) : (
                    dimensionsForSelectedEntity.map((dimension) => (
                        <DimensionRow key={dimension.id} dimension={dimension} />
                    ))
                )}
            </Section>
        </div>
    )
}

function Section({ label, count, children }: { label: string; count: number; children: React.ReactNode }): JSX.Element {
    return (
        <div>
            <div className="flex items-baseline gap-2 mb-2">
                <h3 className="text-sm font-semibold m-0">{label}</h3>
                <span className="text-xs text-secondary">{count}</span>
            </div>
            <div className="flex flex-col border rounded overflow-hidden">{children}</div>
        </div>
    )
}

function EmptyRow({ text }: { text: string }): JSX.Element {
    return <div className="p-3 text-xs text-secondary italic">{text}</div>
}

function MetricRow({ metric }: { metric: CatalogMetricDTOApi }): JSX.Element {
    const { updateMetric } = useActions(catalogBrowserSceneLogic)
    return (
        <div className="flex items-center gap-2 px-3 py-2 border-b last:border-b-0">
            <span className="font-mono text-sm flex-1 truncate" title={metric.name}>
                {metric.name}
            </span>
            <span className="text-xs text-secondary font-mono">{metric.aggregation}</span>
            <LemonTag size="small" type={STATUS_COLOR[metric.status] ?? 'default'}>
                {STATUS_LABEL[metric.status] ?? metric.status}
            </LemonTag>
            {metric.status === 'proposed' && (
                <ReviewButtons
                    onAccept={() => updateMetric(metric.id, { status: 'accepted' })}
                    onReject={() => updateMetric(metric.id, { status: 'rejected' })}
                />
            )}
        </div>
    )
}

function DimensionRow({ dimension }: { dimension: CatalogDimensionDTOApi }): JSX.Element {
    const { updateDimension } = useActions(catalogBrowserSceneLogic)
    return (
        <div className="flex items-center gap-2 px-3 py-2 border-b last:border-b-0">
            <span className="font-mono text-sm flex-1 truncate" title={dimension.name}>
                {dimension.name}
            </span>
            <LemonTag size="small" type={STATUS_COLOR[dimension.status] ?? 'default'}>
                {STATUS_LABEL[dimension.status] ?? dimension.status}
            </LemonTag>
            {dimension.status === 'proposed' && (
                <ReviewButtons
                    onAccept={() => updateDimension(dimension.id, { status: 'accepted' })}
                    onReject={() => updateDimension(dimension.id, { status: 'rejected' })}
                />
            )}
        </div>
    )
}

function ReviewButtons({ onAccept, onReject }: { onAccept: () => void; onReject: () => void }): JSX.Element {
    return (
        <div className="flex gap-1">
            <LemonButton size="xsmall" type="primary" icon={<IconCheck />} onClick={onAccept} tooltip="Accept" />
            <LemonButton size="xsmall" icon={<IconX />} onClick={onReject} tooltip="Reject" />
        </div>
    )
}
