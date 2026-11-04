import { router } from 'kea-router'
import { useState } from 'react'

import { IconExternal, IconRefresh } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { DataModelingNode } from '~/types'

import { LineageGraph } from 'products/data_modeling/frontend/lineage/LineageGraph'
import { lineageIssueMessage } from 'products/data_modeling/frontend/lineage/LineageNode'
import { lineageNodeUrl } from 'products/data_modeling/frontend/lineage/lineageNodeUrl'
import { NODE_TYPE_TAG_SETTINGS } from 'products/data_modeling/frontend/lineage/nodeStyles'

import { QuillMetricCallout } from './components/QuillMetricCallout'
import {
    metricHasExecutableDefinition,
    metricReferencedTableNames,
    referencedTablePreviewQuery,
} from './dataCatalogMetricSceneLogic'
import { DataCatalogMetricApi } from './generated/api.schemas'
import type { MetricLineagePanelProps } from './MetricLineagePanel'

type LineageView = 'graph' | 'table'

const NOTHING_UPSTREAM = "This metric doesn't read any table or view we can trace."
const GRAPH_FRAME_CLASS = 'hidden @[40rem]:block h-[min(45vh,500px)] border border-border rounded-md overflow-hidden'

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
        <Empty className="border border-border rounded-md">
            <EmptyHeader>
                <EmptyTitle>{title}</EmptyTitle>
                <EmptyDescription>{body}</EmptyDescription>
            </EmptyHeader>
            {action && (
                <EmptyContent>
                    <Button variant="outline" onClick={action.onClick}>
                        {action.label}
                    </Button>
                </EmptyContent>
            )}
        </Empty>
    )
}

function MissingLineage({ metric, onRetry }: { metric: DataCatalogMetricApi; onRetry: () => void }): JSX.Element {
    const tableNames = metricReferencedTableNames(metric)

    return (
        <Empty className="border border-border rounded-md">
            <EmptyHeader>
                <EmptyTitle>No lineage for this metric yet</EmptyTitle>
                <EmptyDescription>
                    {tableNames.length > 0
                        ? 'Running this metric reads the tables below, after any views in its query are expanded. Lineage shows up here once the metric is linked to what it reads.'
                        : "We couldn't trace which tables this metric reads. Check that its query runs, then check again."}
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                {tableNames.length > 0 && (
                    <div className="flex flex-wrap justify-center gap-2">
                        {tableNames.map((tableName) => (
                            <Button
                                key={tableName}
                                variant="outline"
                                render={
                                    <LinkPrimitive
                                        to={urls.sqlEditor({ query: referencedTablePreviewQuery(tableName) })}
                                    />
                                }
                                data-attr="data-catalog-metric-lineage-referenced-table"
                            >
                                {tableName}
                            </Button>
                        ))}
                    </div>
                )}
                <Button variant="default" onClick={onRetry} data-attr="data-catalog-metric-lineage-check-again">
                    Check again
                </Button>
            </EmptyContent>
        </Empty>
    )
}

function UpstreamTable({ nodes, emptyState }: { nodes: DataModelingNode[]; emptyState: string }): JSX.Element {
    return (
        <Table size="sm" fullWidth>
            <TableHeader>
                <TableRow>
                    <TableHead expand>Name</TableHead>
                    <TableHead>Type</TableHead>
                </TableRow>
            </TableHeader>
            {nodes.length === 0 ? (
                <TableEmpty>
                    <Text size="xs" variant="muted" className="m-0">
                        {emptyState}
                    </Text>
                </TableEmpty>
            ) : (
                <TableBody>
                    {nodes.map((node) => (
                        <TableRow key={node.id}>
                            <TableCell expand className="max-w-0">
                                <Button
                                    variant="link"
                                    size="inline"
                                    className="max-w-full truncate"
                                    render={<LinkPrimitive to={lineageNodeUrl(node)} />}
                                >
                                    {node.name}
                                </Button>
                            </TableCell>
                            <TableCell>{NODE_TYPE_TAG_SETTINGS[node.type].label}</TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            )}
        </Table>
    )
}

export function QuillMetricLineagePanel({
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
        return (
            <div className="@container">
                <span className="sr-only @[40rem]:hidden" role="status">
                    Loading lineage
                </span>
                <div className="@[40rem]:hidden" aria-hidden="true">
                    <Skeleton className="h-64 w-full" />
                </div>
                <div className={GRAPH_FRAME_CLASS}>
                    <LineageGraph
                        nodes={[]}
                        edges={[]}
                        loading
                        loadingCenter={{ name: metric.name, type: 'metric' }}
                        variant="full"
                    />
                </div>
            </div>
        )
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

    if (lineageProblem === 'missing') {
        return <MissingLineage metric={metric} onRetry={onRetry} />
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
            <QuillMetricCallout
                tone="destructive"
                actions={
                    <Button variant="outline" onClick={onRetry}>
                        Retry
                    </Button>
                }
            >
                Couldn't load lineage.
            </QuillMetricCallout>
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
                <ToggleGroup
                    variant="outline"
                    aria-label="Lineage view"
                    className="hidden @[40rem]:flex"
                    value={[view]}
                    onValueChange={(value: string[]) => value[0] && setView(value[0] as LineageView)}
                >
                    <ToggleGroupItem value="graph">Graph</ToggleGroupItem>
                    <ToggleGroupItem value="table">Table</ToggleGroupItem>
                </ToggleGroup>
                <div className="flex items-center gap-2">
                    <Button
                        variant="outline"
                        size="icon"
                        onClick={onRetry}
                        loading={lineageLoading}
                        tooltip="Refresh lineage"
                        aria-label="Refresh lineage"
                    >
                        <IconRefresh />
                    </Button>
                    <Button
                        variant="outline"
                        size="icon"
                        render={<LinkPrimitive to={urls.models('lineage')} target="_blank" />}
                        tooltip="Open the full graph"
                        aria-label="Open the full graph"
                    >
                        <IconExternal />
                    </Button>
                </div>
            </div>
            {view === 'graph' && (
                <div className={GRAPH_FRAME_CLASS}>
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
