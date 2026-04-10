import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps } from '~/types'

import type { pathsInteractionLogicType } from './pathsInteractionLogicType'
import {
    PathNodeData,
    activateNodes,
    deactivateNodes,
    getForwardConnectedIndices,
    resolveCardOverlaps,
} from './pathUtils'

export type HoverTarget =
    | { type: 'node'; nodeIndex: number }
    | { type: 'link'; sourceIndex: number; targetIndex: number; linkIndex: number }

const DEFAULT_KEY = 'default_paths_interaction_key'
const CLEAR_HOVER_DEBOUNCE_MS = 30

export const pathsInteractionLogic = kea<pathsInteractionLogicType>([
    path((key) => ['scenes', 'paths', 'pathsInteractionLogic', key]),
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_KEY)),

    actions({
        setNodes: (nodes: PathNodeData[], canvasHeight: number) => ({ nodes, canvasHeight }),
        hoverNode: (nodeIndex: number) => ({ nodeIndex }),
        hoverLink: (sourceIndex: number, targetIndex: number, linkIndex: number) => ({
            sourceIndex,
            targetIndex,
            linkIndex,
        }),
        requestClearHover: true,
        clearHover: true,
        setCardHovered: (hovered: boolean) => ({ hovered }),
    }),

    reducers({
        nodes: [
            [] as PathNodeData[],
            {
                setNodes: (_, { nodes }) => nodes,
            },
        ],
        canvasHeight: [
            0 as number,
            {
                setNodes: (_, { canvasHeight }) => canvasHeight,
            },
        ],
        hoverTarget: [
            null as HoverTarget | null,
            {
                hoverNode: (_, { nodeIndex }) => ({ type: 'node', nodeIndex }),
                hoverLink: (_, { sourceIndex, targetIndex, linkIndex }) => ({
                    type: 'link',
                    sourceIndex,
                    targetIndex,
                    linkIndex,
                }),
                clearHover: () => null,
                setNodes: () => null,
            },
        ],
        cardHovered: [
            false,
            {
                setCardHovered: (_, { hovered }) => hovered,
                clearHover: () => false,
            },
        ],
    }),

    listeners(({ actions, cache }) => ({
        requestClearHover: () => {
            clearTimeout(cache.clearHoverTimeout)
            cache.clearHoverTimeout = setTimeout(() => {
                actions.clearHover()
            }, CLEAR_HOVER_DEBOUNCE_MS)
        },
        hoverNode: () => {
            clearTimeout(cache.clearHoverTimeout)
        },
        hoverLink: () => {
            clearTimeout(cache.clearHoverTimeout)
        },
        setCardHovered: ({ hovered }) => {
            if (hovered) {
                clearTimeout(cache.clearHoverTimeout)
            }
        },
    })),

    selectors({
        activeIndices: [
            (s) => [s.hoverTarget, s.nodes],
            (
                hoverTarget: HoverTarget | null,
                nodes: PathNodeData[]
            ): { nodeIndices: Set<number>; linkIndices: Set<number> } => {
                const empty = { nodeIndices: new Set<number>(), linkIndices: new Set<number>() }
                if (!hoverTarget || nodes.length === 0) {
                    return empty
                }

                if (hoverTarget.type === 'node') {
                    const node = nodes.find((n) => n.index === hoverTarget.nodeIndex)
                    if (!node) {
                        return empty
                    }
                    const forward = getForwardConnectedIndices(node)
                    for (const link of node.targetLinks) {
                        forward.linkIndices.add(link.index)
                        forward.nodeIndices.add(link.source.index)
                    }
                    return forward
                }

                const source = nodes.find((n) => n.index === hoverTarget.sourceIndex)
                const target = nodes.find((n) => n.index === hoverTarget.targetIndex)
                if (!source || !target) {
                    return empty
                }
                const forward = getForwardConnectedIndices(target)
                forward.nodeIndices.add(source.index)
                forward.linkIndices.add(hoverTarget.linkIndex)
                return forward
            },
        ],
        resolvedNodeCards: [
            (s) => [s.nodes, s.activeIndices, s.canvasHeight],
            (
                nodes: PathNodeData[],
                activeIndices: { nodeIndices: Set<number>; linkIndices: Set<number> },
                canvasHeight: number
            ): PathNodeData[] => {
                const withState =
                    activeIndices.nodeIndices.size > 0
                        ? activateNodes(nodes, activeIndices.nodeIndices)
                        : deactivateNodes(nodes)
                return resolveCardOverlaps(withState, canvasHeight)
            },
        ],
    }),
])
