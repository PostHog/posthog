import '@xyflow/react/dist/style.css'

import { Background, BackgroundVariant, Controls, Panel, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import { ServiceMapDetails } from './ServiceMapDetails'
import { ServiceMapNode } from './ServiceMapNode'

const NODE_TYPES = { service: ServiceMapNode }
// Calls into a callee that fails this often draw in the danger color, the same threshold as a failing status.
const FAILING_EDGE_ERROR_RATE = 0.05

export function ServiceMapTab(): JSX.Element {
    const { serviceMap, serviceMapLayout, serviceMapLoading, serviceMapLoadError, selectedMapServiceName } =
        useValues(applicationObservabilityLogic)
    const { setSelectedMapService } = useActions(applicationObservabilityLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    const edges = useMemo(
        () =>
            (serviceMapLayout?.edges ?? []).map((edge) => ({
                ...edge,
                style: {
                    strokeWidth: edge.data?.width ?? 1,
                    stroke: (edge.data?.errorRate ?? 0) >= FAILING_EDGE_ERROR_RATE ? 'var(--danger)' : undefined,
                },
            })),
        [serviceMapLayout]
    )
    const nodes = serviceMapLayout?.nodes ?? []

    return (
        <div className="flex flex-col gap-2">
            {serviceMapLoadError && (
                <LemonBanner type="error">
                    {serviceMap
                        ? "Couldn't refresh the map. Showing the last successful results."
                        : "Couldn't load the map. Try again shortly."}
                </LemonBanner>
            )}
            {serviceMap && (
                <span className="text-xs text-secondary">
                    Built from {serviceMap.trace_count.toLocaleString()} sampled traces. Line width shows the share of
                    calls. Select a service to see its health and calls.
                </span>
            )}
            <div className="relative h-[560px] rounded border bg-surface-primary" data-attr="apm-service-map">
                {nodes.length === 0 ? (
                    <div className="flex h-full items-center justify-center p-4 text-center text-secondary">
                        {serviceMapLoading || !serviceMap ? (
                            <Spinner />
                        ) : (
                            'No services in this environment and time range. Send traces to see the map.'
                        )}
                    </div>
                ) : (
                    <ReactFlowProvider>
                        <ReactFlow
                            colorMode={isDarkModeOn ? 'dark' : 'light'}
                            nodes={nodes}
                            edges={edges}
                            nodeTypes={NODE_TYPES}
                            onNodeClick={(_, node) =>
                                setSelectedMapService(selectedMapServiceName === node.id ? null : node.id)
                            }
                            onPaneClick={() => setSelectedMapService(null)}
                            nodesDraggable={false}
                            nodesConnectable={false}
                            elementsSelectable={false}
                            nodesFocusable={false}
                            fitView
                            minZoom={0.1}
                            maxZoom={2}
                            proOptions={{ hideAttribution: true }}
                        >
                            <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
                            <Controls showInteractive={false} position="bottom-left" />
                            <Panel position="top-right">
                                <ServiceMapDetails />
                            </Panel>
                        </ReactFlow>
                    </ReactFlowProvider>
                )}
            </div>
        </div>
    )
}
