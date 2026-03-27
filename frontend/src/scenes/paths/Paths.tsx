import './Paths.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelPathsFilter } from '~/queries/schema/schema-general'
import { shouldQueryBeAsync } from '~/queries/utils'

import { PathNodeCard } from './PathNodeCard'
import { pathsDataLogic } from './pathsDataLogic'
import { pathsInteractionLogic } from './pathsInteractionLogic'
import type { PathNodeData } from './pathUtils'
import type { PathsHoverHandlers } from './renderPaths'
// eslint-disable-next-line import/no-cycle
import { renderPaths } from './renderPaths'

const DEFAULT_PATHS_ID = 'default_paths'
export const HIDE_PATH_CARD_HEIGHT = 30
export const FALLBACK_CANVAS_WIDTH = 1000
const FALLBACK_CANVAS_HEIGHT = 0
const CANVAS_RESIZE_DEBOUNCE_MS = 50

export function Paths(): JSX.Element {
    const canvasRef = useRef<HTMLDivElement>(null)
    const canvasContainerRef = useRef<HTMLDivElement>(null)
    const { width: rawCanvasWidth, height: rawCanvasHeight } = useResizeObserver({ ref: canvasRef })
    const [canvasWidth, setCanvasWidth] = useState(FALLBACK_CANVAS_WIDTH)
    const [canvasHeight, setCanvasHeight] = useState(FALLBACK_CANVAS_HEIGHT)

    // Debounce canvas dimension updates to prevent rapid SVG recreation from ResizeObserver.
    // We do NOT remove data-stable here — the render effect below removes it only when the SVG
    // is actually being recreated. Removing it here would cause data-stable to disappear for the
    // entire debounce window on every resize, making Playwright's waitForSelector time out.
    useEffect(() => {
        const timer = setTimeout(() => {
            setCanvasWidth(rawCanvasWidth ?? FALLBACK_CANVAS_WIDTH)
            setCanvasHeight(rawCanvasHeight ?? FALLBACK_CANVAS_HEIGHT)
        }, CANVAS_RESIZE_DEBOUNCE_MS)
        return () => clearTimeout(timer)
    }, [rawCanvasWidth, rawCanvasHeight])

    const { insight, insightProps } = useValues(insightLogic)
    const { insightQuery, paths, pathsFilter, funnelPathsFilter, insightDataLoading, insightDataError, theme } =
        useValues(pathsDataLogic(insightProps))
    const { loadData } = useActions(insightDataLogic(insightProps))

    const interactionLogic = pathsInteractionLogic(insightProps)
    const { resolvedNodeCards, activeIndices } = useValues(interactionLogic)
    const { setNodes, hoverNode, hoverLink, clearHover, requestClearHover, setCardHovered } =
        useActions(interactionLogic)

    // eslint-disable-next-line react-hooks/exhaustive-deps -- kea action creators are stable references
    const hoverHandlers = useMemo<PathsHoverHandlers>(
        () => ({
            onNodesReady: (nodes: PathNodeData[]) => setNodes(nodes, canvasHeight),
            onNodeHover: hoverNode,
            onLinkHover: hoverLink,
            onHoverClear: requestClearHover,
            isCardHovered: () => interactionLogic.values.cardHovered,
        }),
        [canvasHeight]
    )

    useLayoutEffect(() => {
        canvasRef.current?.querySelectorAll<SVGPathElement>('path[id^="path-"]').forEach((el) => {
            const pathIndex = Number(el.id.replace('path-', ''))
            el.setAttribute(
                'stroke',
                activeIndices.linkIndices.has(pathIndex) ? 'var(--paths-link-hover)' : 'var(--paths-link)'
            )
        })
    }, [activeIndices])

    const id = `'${insight?.short_id || DEFAULT_PATHS_ID}'`

    useEffect(() => {
        clearHover()

        const elements = canvasContainerRef.current?.querySelectorAll(`.Paths__canvas`)
        elements?.forEach((node) => node?.parentNode?.removeChild(node))

        if (canvasRef.current) {
            canvasRef.current.removeAttribute('data-stable')
        }

        renderPaths(
            canvasRef,
            canvasWidth,
            canvasHeight,
            paths,
            pathsFilter || {},
            funnelPathsFilter || ({} as FunnelPathsFilter),
            hoverHandlers
        )

        if (canvasRef.current) {
            canvasRef.current.setAttribute('data-stable', 'true')
        }

        return () => {
            const elements = canvasContainerRef.current?.querySelectorAll(`.Paths__canvas`)
            elements?.forEach((node) => node?.parentNode?.removeChild(node))
        }
    }, [paths, insightDataLoading, canvasWidth, canvasHeight, theme, pathsFilter, funnelPathsFilter, hoverHandlers])

    const handleCardMouseEnter = (node: PathNodeData): void => {
        setCardHovered(true)
        hoverNode(node.index)
    }

    const handleCardMouseLeave = (): void => {
        // Setting cardHovered=false immediately re-enables SVG handlers. If the mouse
        // lands on an SVG element within the 30ms debounce window, that handler fires
        // a new hoverNode/hoverLink which cancels the pending clearHover — so the
        // transition from card→SVG hover is seamless.
        setCardHovered(false)
        requestClearHover()
    }

    if (insightDataError) {
        return (
            <InsightErrorState
                query={insightQuery}
                excludeDetail
                onRetry={() => {
                    loadData(shouldQueryBeAsync(insightQuery) ? 'force_async' : 'force_blocking')
                }}
            />
        )
    }

    return (
        <div className="h-full w-full overflow-auto" id={id} ref={canvasContainerRef}>
            <div
                ref={canvasRef}
                className="Paths"
                data-attr="paths-viz"
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        '--paths-node': theme?.['preset-1'] || '#000000',
                        '--paths-node-start-or-end': theme?.['preset-2'] || '#000000',
                        '--paths-link': theme?.['preset-1'] || '#000000',
                        '--paths-link-hover': theme?.['preset-2'] || '#000000',
                        '--paths-dropoff': 'rgba(220,53,69,0.7)',
                    } as React.CSSProperties
                }
            >
                {!insightDataLoading && paths && paths.nodes.length === 0 && !insightDataError && <InsightEmptyState />}
                {!insightDataError &&
                    resolvedNodeCards.map((node, idx) => (
                        <PathNodeCard
                            key={idx}
                            node={node}
                            insightProps={insightProps}
                            canvasHeight={canvasHeight}
                            onMouseEnter={() => handleCardMouseEnter(node)}
                            onMouseLeave={handleCardMouseLeave}
                        />
                    ))}
            </div>
        </div>
    )
}
