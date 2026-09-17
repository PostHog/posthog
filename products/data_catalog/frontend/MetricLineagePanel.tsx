import { router } from 'kea-router'
import { useState } from 'react'

import { IconExternal, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { DataModelingNode } from '~/types'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'
import { lineageIssueMessage } from 'products/data_modeling/frontend/lineage/LineageNode'
import { lineageNodeUrl } from 'products/data_modeling/frontend/lineage/lineageNodeUrl'
import { NODE_TYPE_TAG_SETTINGS } from 'products/data_modeling/frontend/lineage/nodeStyles'

import { LineageLoadProblem, metricHasExecutableDefinition, MetricLineage } from './dataCatalogMetricSceneLogic'
import { DataCatalogMetricApi } from './generated/api.schemas'

type LineageView = 'graph' | 'table'

const NOTHING_UPSTREAM = "This metric doesn't read any table or view we can trace."

function LineageMessage({
    title,
    body,
    action,
}: {
    title: string
    body: string
    action?: { label: string; onClick: () => void }
}): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-2 border rounded p-6 bg-surface-primary">
            <span className="font-semibold">{title}</span>
            <span className="text-secondary">{body}</span>
            {action && (
                <LemonButton type="secondary" size="small" onClick={action.onClick}>
                    {action.label}
                </LemonButton>
            )}
        </div>
    )
}

function UpstreamTable({ nodes, emptyState }: { nodes: DataModelingNode[]; emptyState: string }): JSX.Element {
    return (
        <LemonTable
            size="small"
            emptyState={emptyState}
            columns={[
                {
                    key: 'name',
                    title: 'Name',
                    render: (_, node) => <LemonTableLink to={lineageNodeUrl(node)} title={node.name} />,
                },
                { key: 'type', title: 'Type', render: (_, node) => NODE_TYPE_TAG_SETTINGS[node.type].label },
            ]}
            dataSource={nodes}
        />
    )
}

export interface MetricLineagePanelProps {
    metric: DataCatalogMetricApi
    lineage: MetricLineage | null
    lineageLoading: boolean
    lineageProblem: LineageLoadProblem | null
    onRetry: () => void
    onEditDefinition: () => void
}

export function MetricLineagePanel({
    metric,
    lineage,
    lineageLoading,
    lineageProblem,
    onRetry,
    onEditDefinition,
}: MetricLineagePanelProps): JSX.Element {
    const [view, setView] = useState<LineageView>('graph')

    if (!metricHasExecutableDefinition(metric)) {
        return (
            <LineageMessage
                title="No lineage yet"
                body="Lineage shows the tables and views a metric reads. Add a query definition to see it."
                action={{ label: 'Edit definition', onClick: onEditDefinition }}
            />
        )
    }

    if (lineageLoading && !lineage) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    if (lineageProblem === 'not_ready') {
        return (
            <LineageMessage
                title="Lineage is being prepared"
                body="This usually takes a few seconds."
                action={{ label: 'Refresh', onClick: onRetry }}
            />
        )
    }

    if (lineageProblem === 'no_warehouse_access') {
        return (
            <LineageMessage
                title="Lineage needs data warehouse access"
                body="Ask an admin for viewer access to the data warehouse to see which tables this metric reads."
            />
        )
    }

    if (lineageProblem === 'failed') {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: onRetry }}>
                Couldn't load lineage.
            </LemonBanner>
        )
    }

    const nodes = lineage?.nodes ?? []
    const edges = lineage?.edges ?? []
    const currentNode = nodes.find((node) => node.metric_id === metric.id)
    const upstreamNodes = nodes.filter((node) => node.id !== currentNode?.id)
    const upstreamEmptyState = currentNode?.lineage_issue
        ? lineageIssueMessage(currentNode.lineage_issue)
        : NOTHING_UPSTREAM

    return (
        <div className="@container flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-end @[40rem]:justify-between gap-2">
                <LemonSegmentedButton
                    className="hidden @[40rem]:block"
                    value={view}
                    onChange={setView}
                    options={[
                        { value: 'graph', label: 'Graph' },
                        { value: 'table', label: 'Table' },
                    ]}
                    size="small"
                />
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={onRetry}
                        loading={lineageLoading}
                        icon={<IconRefresh />}
                        tooltip="Refresh lineage"
                        aria-label="Refresh lineage"
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.models('lineage')}
                        targetBlank
                        tooltip="Open the full graph"
                        aria-label="Open the full graph"
                        icon={<IconExternal />}
                    />
                </div>
            </div>
            {view === 'graph' && (
                <div className="hidden @[40rem]:block h-[min(45vh,500px)] border border-border rounded-md overflow-hidden">
                    <LineageGraph
                        nodes={nodes}
                        edges={edges}
                        currentNodeId={currentNode?.id}
                        variant="full"
                        interactive
                        showControls
                        emptyMessage={NOTHING_UPSTREAM}
                        nodeCallbacks={(node) => ({
                            onClick:
                                node.id === currentNode?.id
                                    ? undefined
                                    : () => router.actions.push(lineageNodeUrl(node)),
                        })}
                    />
                </div>
            )}
            <div className={view === 'graph' ? '@[40rem]:hidden' : undefined}>
                <UpstreamTable nodes={upstreamNodes} emptyState={upstreamEmptyState} />
            </div>
        </div>
    )
}
