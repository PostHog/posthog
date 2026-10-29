import '@xyflow/react/dist/style.css'

import { Background, BackgroundVariant, Controls, Panel, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import type { ServiceMapWarning } from './applicationObservabilityLogic'
import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import { ServiceMapDetails } from './ServiceMapDetails'
import { ServiceMapNode } from './ServiceMapNode'

const NODE_TYPES = { service: ServiceMapNode }
// Calls into a callee that fails this often draw in the danger color, the same threshold as a failing status.
const FAILING_EDGE_ERROR_RATE = 0.05

function warningMessage(warning: Exclude<ServiceMapWarning, null>, hasMap: boolean): string {
    switch (warning) {
        case 'map':
            return hasMap
                ? "Couldn't refresh the map. Showing the last successful results."
                : "Couldn't load the map. Check your connection and try again."
        case 'layout':
            return "Couldn't draw the map. Try again."
        case 'health':
            return "Couldn't load service health, so the map shows calls without health. Try again."
    }
}

export function ServiceMapTab(): JSX.Element {
    const { serviceMap, serviceMapLayout, serviceMapLoading, serviceMapWarning } =
        useValues(applicationObservabilityLogic)
    const { setSelectedMapService, layoutServiceMap, loadServiceMap, loadServicesHealth } =
        useActions(applicationObservabilityLogic)
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
            {serviceMapWarning && (
                <LemonBanner
                    type={serviceMapWarning === 'health' ? 'warning' : 'error'}
                    action={{
                        children: 'Try again',
                        onClick: () =>
                            serviceMapWarning === 'map'
                                ? loadServiceMap()
                                : serviceMapWarning === 'layout'
                                  ? layoutServiceMap()
                                  : loadServicesHealth(),
                    }}
                >
                    {warningMessage(serviceMapWarning, !!serviceMapLayout?.nodes.length)}
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
                            onPaneClick={() => setSelectedMapService(null)}
                            nodesDraggable={false}
                            nodesConnectable={false}
                            // Each node renders its own button, which is the focus and keyboard target.
                            // Selectable elements keep pointer events on the node so the button gets clicks.
                            elementsSelectable
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
