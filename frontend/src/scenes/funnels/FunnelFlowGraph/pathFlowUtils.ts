import { Edge, Node } from '@xyflow/react'

import { FunnelsQuery, NodeKind, PathsLink, PathsQuery } from '~/queries/schema/schema-general'
import { FunnelPathType, PathType } from '~/types'

export const PATH_NODE_WIDTH = 180
export const PATH_NODE_HEIGHT = 40

export interface PathFlowNodeData extends Record<string, unknown> {
    eventName: string
    displayName: string
    count: number
}

export interface PathFlowEdgeData extends Record<string, unknown> {
    value: number
    maxValue: number
    isDropOff?: boolean
}

export interface PathExpansion {
    stepIndex: number
    pathType: FunnelPathType
    dropOff: boolean
}

export interface BridgeConfig {
    sourceStepId: string | null
    targetStepId: string | null
    isDropOff: boolean
    hiddenEdgeId: string | null
}

export function pathExpansionCacheKey(expansion: PathExpansion): string {
    return `${expansion.stepIndex}-${expansion.pathType}-${expansion.dropOff}`
}

export function bridgeConfigForExpansion(expansion: PathExpansion): BridgeConfig {
    const { stepIndex, pathType, dropOff } = expansion

    if (pathType === FunnelPathType.between) {
        return {
            sourceStepId: `step-${stepIndex - 1}`,
            targetStepId: `step-${stepIndex}`,
            isDropOff: false,
            hiddenEdgeId: `edge-${stepIndex - 1}`,
        }
    }

    if (pathType === FunnelPathType.before) {
        return {
            sourceStepId: null,
            targetStepId: `step-${stepIndex}`,
            isDropOff: dropOff,
            hiddenEdgeId: null,
        }
    }

    // after (with or without dropOff)
    return {
        sourceStepId: `step-${stepIndex}`,
        targetStepId: null,
        isDropOff: dropOff,
        hiddenEdgeId: null,
    }
}

function stripStepPrefix(name: string): string {
    return name.replace(/^[0-9]+_/, '')
}

export function extractLayerIndex(name: string): number {
    const match = name.match(/^([0-9]+)_/)
    return match ? parseInt(match[1], 10) : 0
}

function formatDisplayName(rawName: string): string {
    const name = stripStepPrefix(rawName)
    try {
        const url = new URL(name)
        const display = url.pathname + url.search
        return display.length > 28 ? display.substring(0, 20) + '...' + display.slice(-7) : display
    } catch {
        return name.length > 28 ? name.substring(0, 20) + '...' + name.slice(-7) : name
    }
}

interface PathFlowGraphElements {
    nodes: Node<PathFlowNodeData>[]
    edges: Edge<PathFlowEdgeData>[]
}

export function buildPathFlowElements(
    pathsLinks: PathsLink[],
    sourceStepId: string | null,
    targetStepId: string | null,
    isDropOff?: boolean,
    funnelStepByEventName?: Map<string, string>
): PathFlowGraphElements {
    if (pathsLinks.length === 0) {
        return { nodes: [], edges: [] }
    }

    const nodeMap = new Map<string, { eventName: string; displayName: string; count: number; layer: number }>()
    const maxValue = Math.max(...pathsLinks.map((l) => l.value))

    for (const link of pathsLinks) {
        for (const name of [link.source, link.target]) {
            if (!nodeMap.has(name)) {
                nodeMap.set(name, {
                    eventName: stripStepPrefix(name),
                    displayName: formatDisplayName(name),
                    count: 0,
                    layer: extractLayerIndex(name),
                })
            }
        }
        const sourceNode = nodeMap.get(link.source)!
        sourceNode.count = Math.max(sourceNode.count, link.value)
        const targetNode = nodeMap.get(link.target)!
        targetNode.count = Math.max(targetNode.count, link.value)
    }

    const nodeReplacement = new Map<string, string>()
    if (funnelStepByEventName) {
        for (const [rawName, data] of nodeMap) {
            const funnelStepId = funnelStepByEventName.get(data.eventName)
            if (funnelStepId) {
                nodeReplacement.set(rawName, funnelStepId)
            }
        }
    }

    function resolveNodeId(rawName: string): string {
        return nodeReplacement.get(rawName) ?? `path-${rawName}`
    }

    const nodes: Node<PathFlowNodeData>[] = []

    for (const [rawName, data] of nodeMap) {
        if (nodeReplacement.has(rawName)) {
            continue
        }
        nodes.push({
            id: `path-${rawName}`,
            type: 'pathNode',
            data: {
                eventName: data.eventName,
                displayName: data.displayName,
                count: data.count,
            },
            position: { x: 0, y: 0 },
            width: PATH_NODE_WIDTH,
            height: PATH_NODE_HEIGHT,
            draggable: false,
            connectable: false,
        })
    }

    const edges: Edge<PathFlowEdgeData>[] = []
    for (let i = 0; i < pathsLinks.length; i++) {
        const link = pathsLinks[i]
        const resolvedSource = resolveNodeId(link.source)
        const resolvedTarget = resolveNodeId(link.target)
        if (resolvedSource === resolvedTarget) {
            continue
        }
        edges.push({
            id: `path-edge-${i}-${link.source}-${link.target}`,
            source: resolvedSource,
            target: resolvedTarget,
            type: 'pathFlow',
            sourceHandle: `${resolvedSource}-source`,
            targetHandle: `${resolvedTarget}-target`,
            data: { value: link.value, maxValue },
        })
    }

    const minLayer = Math.min(...Array.from(nodeMap.values()).map((n) => n.layer))
    const maxLayer = Math.max(...Array.from(nodeMap.values()).map((n) => n.layer))

    const bridgeFromSource: Edge<PathFlowEdgeData>[] = []
    const bridgeToTarget: Edge<PathFlowEdgeData>[] = []

    for (const [rawName, data] of nodeMap) {
        const resolvedId = resolveNodeId(rawName)
        if (sourceStepId && data.layer === minLayer && resolvedId !== sourceStepId) {
            bridgeFromSource.push({
                id: `bridge-from-${sourceStepId}-${resolvedId}`,
                source: sourceStepId,
                target: resolvedId,
                type: 'pathFlow',
                sourceHandle: `${sourceStepId}-source`,
                targetHandle: `${resolvedId}-target`,
                data: { value: data.count, maxValue, isDropOff },
            })
        }
        if (targetStepId && data.layer === maxLayer && resolvedId !== targetStepId) {
            bridgeToTarget.push({
                id: `bridge-to-${targetStepId}-${resolvedId}`,
                source: resolvedId,
                target: targetStepId,
                type: 'pathFlow',
                sourceHandle: `${resolvedId}-source`,
                targetHandle: `${targetStepId}-target`,
                data: { value: data.count, maxValue },
            })
        }
    }

    return {
        nodes,
        edges: [...bridgeFromSource, ...edges, ...bridgeToTarget],
    }
}

export function buildPathsQuery(expansion: PathExpansion, querySource: FunnelsQuery): PathsQuery {
    const stepNumber = expansion.stepIndex + 1
    const funnelStep = expansion.dropOff ? stepNumber * -1 : stepNumber
    return {
        kind: NodeKind.PathsQuery,
        funnelPathsFilter: {
            funnelPathType: expansion.pathType,
            funnelStep,
            funnelSource: querySource,
        },
        pathsFilter: {
            includeEventTypes: [PathType.PageView, PathType.CustomEvent],
            edgeLimit: 15,
        },
        dateRange: {
            date_from: querySource.dateRange?.date_from,
        },
    }
}
