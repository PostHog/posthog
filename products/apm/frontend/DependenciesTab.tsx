import '@xyflow/react/dist/style.css'

import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonButton, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { FAILING_ERROR_RATE } from './dependencies'
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

export function DependenciesTab(): JSX.Element {
    const {
        dependencies,
        dependenciesLoading,
        dependenciesLoadError,
        dependencyLayout,
        dependencyService,
        edges,
        serviceNames,
        split,
    } = useValues(dependenciesLogic)
    const { setDependencyService, loadDependencies } = useActions(dependenciesLogic)
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

    return (
        <div className="flex flex-col gap-2">
            {dependenciesLoadError && (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadDependencies() }}>
                    {edges.length > 0
                        ? "Couldn't refresh dependencies. Showing the last successful results."
                        : "Couldn't load dependencies. Check your connection and try again."}
                </LemonBanner>
            )}
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
                    options={[
                        { value: null, label: 'All services' },
                        ...serviceNames.map((name) => ({ value: name, label: name })),
                    ]}
                    data-attr="apm-dependencies-service"
                />
                <span className="text-xs text-secondary">
                    Dashed boxes are databases, queues and hosts that send no spans, named by their callers. Select a
                    service to see who calls it and what it calls.
                </span>
            </div>
            <div className="relative h-[480px] rounded border bg-surface-primary" data-attr="apm-dependencies-map">
                {nodes.length === 0 ? (
                    <div className="flex h-full items-center justify-center p-4 text-center text-secondary">
                        <DependencyMapPlaceholder />
                    </div>
                ) : (
                    <ReactFlowProvider>
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
                    />
                    <DependencyTable
                        title={`Downstream: calls from ${dependencyService}`}
                        edges={split.downstream}
                        loading={dependenciesLoading}
                        emptyState={`${dependencyService} called nothing in this time range.`}
                        dataAttr="apm-dependencies-downstream"
                    />
                </div>
            ) : (
                <DependencyTable
                    title="All calls"
                    edges={edges}
                    loading={dependenciesLoading}
                    emptyState="No calls between services in this environment and time range."
                    dataAttr="apm-dependencies-all"
                />
            )}
        </div>
    )
}
