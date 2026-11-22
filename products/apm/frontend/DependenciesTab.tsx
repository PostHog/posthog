import '@xyflow/react/dist/style.css'

import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonButton, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import { DRAWN_EDGE_CAP, FAILING_ERROR_RATE } from './dependencies'
import { dependenciesLogic } from './dependenciesLogic'
import { DependencyNode } from './DependencyNode'
import { DependencyTable } from './DependencyTable'

const NODE_TYPES = { dependency: DependencyNode }

function DependencyMapPlaceholder(): JSX.Element {
    const { dependencies, dependenciesLoading, dependenciesLoadError, dependencyLayout, dependencyLayoutError, edges } =
        useValues(dependenciesLogic)
    const { layoutDependencies } = useActions(dependenciesLogic)

    if (dependencyLayoutError && edges.length > 0) {
        return (
            <div className="flex flex-col items-center gap-2">
                <span>Couldn't draw the dependency map.</span>
                <LemonButton type="secondary" size="small" onClick={() => layoutDependencies()}>
                    Try again
                </LemonButton>
            </div>
        )
    }
    if ((dependenciesLoading && !dependencies) || (edges.length > 0 && !dependencyLayout)) {
        return <Spinner />
    }
    return (
        <>
            {dependenciesLoadError
                ? "Couldn't load dependencies."
                : 'No calls between services in this environment and time range.'}
        </>
    )
}

// A load that is replaced keeps running on the server and holds one of the few concurrent query slots,
// so the service can change only once the current load finishes.
const LOADING_REASON = 'Loading dependencies…'

function DependenciesTooHeavyBanner({ detail }: { detail: string }): JSX.Element {
    const { serviceNames, dependencyService, dependenciesLoading } = useValues(dependenciesLogic)
    const { setDependencyService } = useActions(dependenciesLogic)
    const { timeRange } = useValues(applicationObservabilityLogic)
    const { setTimeRange } = useActions(applicationObservabilityLogic)

    return (
        <LemonBanner type="warning">
            <div className="flex flex-col gap-2">
                <span>{detail}</span>
                <div className="flex flex-wrap items-center gap-2">
                    {timeRange !== '-15m' && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => setTimeRange('-15m')}
                            data-attr="apm-dependencies-last-15-minutes"
                        >
                            Last 15 minutes
                        </LemonButton>
                    )}
                    {!dependencyService && serviceNames.length > 0 && (
                        <LemonSelect
                            size="small"
                            placeholder="Pick a service"
                            value={null}
                            onChange={(value) => value && setDependencyService(value)}
                            disabledReason={dependenciesLoading ? LOADING_REASON : undefined}
                            options={serviceNames.map((name) => ({ value: name, label: name }))}
                            data-attr="apm-dependencies-pick-service"
                        />
                    )}
                </div>
            </div>
        </LemonBanner>
    )
}

export function DependenciesTab(): JSX.Element {
    const {
        dependencies,
        dependenciesLoading,
        dependenciesLoadError,
        dependenciesLoadErrorDetail,
        dependencyLayout,
        dependencyLayoutKey,
        dependencyLayoutLoading,
        dependencyService,
        drawableEdges,
        drawnEdges,
        edges,
        serviceNames,
        showAllDependencies,
        split,
    } = useValues(dependenciesLogic)
    const { setDependencyService, loadDependencies, setShowAllDependencies } = useActions(dependenciesLogic)
    const canCap = !dependencyService && drawableEdges.length > DRAWN_EDGE_CAP
    const { isDarkModeOn } = useValues(themeLogic)

    const flowEdges = useMemo(
        () =>
            (dependencyLayout?.edges ?? []).map((edge) => ({
                ...edge,
                style: {
                    strokeWidth: edge.data?.width ?? 1,
                    stroke: (edge.data?.errorRate ?? 0) >= FAILING_ERROR_RATE ? 'var(--danger)' : undefined,
                },
            })),
        [dependencyLayout]
    )
    const nodes = dependencyLayout?.nodes ?? []
    const serviceLink = (service: string): { onClick: () => void } => ({
        onClick: () => setDependencyService(service),
    })

    return (
        <div className="flex flex-col gap-2">
            {dependenciesLoadErrorDetail ? (
                <DependenciesTooHeavyBanner detail={dependenciesLoadErrorDetail} />
            ) : dependenciesLoadError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadDependencies() }}>
                    {edges.length > 0
                        ? "Couldn't refresh dependencies. Showing the last successful results."
                        : "Couldn't load dependencies. Check your connection and try again."}
                </LemonBanner>
            ) : null}
            {dependencies?.truncated && (
                <LemonBanner type="info">
                    Showing the busiest {edges.length} calls. Pick a shorter time range to see the rest.
                </LemonBanner>
            )}
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    size="small"
                    value={dependencyService}
                    onChange={(value) => setDependencyService(value)}
                    disabledReason={dependenciesLoading ? LOADING_REASON : undefined}
                    options={[
                        { value: null, label: 'All services' },
                        ...serviceNames.map((name) => ({ value: name, label: name })),
                    ]}
                    data-attr="apm-dependencies-service"
                />
                {dependencies?.sampled && (
                    <span className="text-xs text-secondary" data-attr="apm-dependencies-sampled">
                        Built from {dependencies.trace_count.toLocaleString()} sampled traces.
                    </span>
                )}
                <span className="text-xs text-secondary">
                    Dashed boxes are databases, queues and hosts that send no spans, named by their callers. Select a
                    service to see who calls it and what it calls.
                </span>
            </div>
            {canCap && (
                <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
                    <span data-attr="apm-dependencies-capped">
                        {showAllDependencies
                            ? `Showing all ${drawableEdges.length} calls.`
                            : `Showing the ${drawnEdges.length} busiest of ${drawableEdges.length} calls. Pick a service to see all of its calls.`}
                    </span>
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={() => setShowAllDependencies(!showAllDependencies)}
                        disabledReason={dependencyLayoutLoading ? 'Drawing the map…' : undefined}
                        data-attr="apm-dependencies-show-all"
                    >
                        {showAllDependencies ? `Show the ${DRAWN_EDGE_CAP} busiest` : 'Show all'}
                    </LemonButton>
                </div>
            )}
            <div className="relative h-[480px] rounded border bg-surface-primary" data-attr="apm-dependencies-map">
                {nodes.length === 0 ? (
                    <div className="flex h-full items-center justify-center p-4 text-center text-secondary">
                        <DependencyMapPlaceholder />
                    </div>
                ) : (
                    // Remounting on a new set of nodes or edges fits the view again, since fitView only runs on mount.
                    <ReactFlowProvider key={dependencyLayoutKey}>
                        <ReactFlow
                            colorMode={isDarkModeOn ? 'dark' : 'light'}
                            nodes={nodes}
                            edges={flowEdges}
                            nodeTypes={NODE_TYPES}
                            nodesDraggable={false}
                            nodesConnectable={false}
                            elementsSelectable
                            nodesFocusable={false}
                            fitView
                            minZoom={0.1}
                            maxZoom={2}
                            proOptions={{ hideAttribution: true }}
                        >
                            <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
                            <Controls showInteractive={false} position="bottom-left" />
                        </ReactFlow>
                    </ReactFlowProvider>
                )}
            </div>
            {split && dependencyService ? (
                <div className="grid gap-4 lg:grid-cols-2">
                    <DependencyTable
                        title={`Upstream: calls into ${dependencyService}`}
                        edges={split.upstream}
                        loading={dependenciesLoading}
                        emptyState={`Nothing called ${dependencyService} in this time range.`}
                        dataAttr="apm-dependencies-upstream"
                        serviceLink={serviceLink}
                    />
                    <DependencyTable
                        title={`Downstream: calls from ${dependencyService}`}
                        edges={split.downstream}
                        loading={dependenciesLoading}
                        emptyState={`${dependencyService} called nothing in this time range.`}
                        dataAttr="apm-dependencies-downstream"
                        serviceLink={serviceLink}
                    />
                </div>
            ) : (
                <DependencyTable
                    title="All calls"
                    edges={edges}
                    loading={dependenciesLoading}
                    emptyState="No calls between services in this environment and time range."
                    dataAttr="apm-dependencies-all"
                    serviceLink={serviceLink}
                />
            )}
        </div>
    )
}
