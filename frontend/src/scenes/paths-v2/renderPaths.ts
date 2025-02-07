import * as d3 from 'd3'
import * as Sankey from 'd3-sankey'
import { D3Selector } from 'lib/hooks/useD3'
import { stripHTTP } from 'lib/utils'
import { Dispatch, RefObject, SetStateAction } from 'react'

import { FunnelPathsFilter, PathsFilter } from '~/queries/schema'

import { isSelectedPathStartOrEnd, PathNodeData, PathTargetLink } from './pathUtils'
import { Paths } from './types'

/*
 * Canvas
 */

const FALLBACK_CANVAS_WIDTH = 1000
const FALLBACK_CANVAS_HEIGHT = 0

/*
 * Node
 */

// We want the border radius to overlap the links. For this we subtract the border radius of both
// sides from the node width, and add it back to the svg element that is moved left by the border radius.
//
// We also expand the canvas margin by the border radius on both sides to make sure the nodes are not cut off.
const NODE_BORDER_RADIUS = 6
const NODE_WIDTH = 48 - 2 * NODE_BORDER_RADIUS

/*
 * Node label
 */

export const PATH_NODE_CARD_WIDTH = 240
export const PATH_NODE_CARD_HEIGHT = 44
const PATH_NODE_CARD_MARGIN_TOP = 20
const PATH_NODE_CARD_MARGIN_BOTTOM = 10
export const PATH_NODE_CARD_TOP_OFFSET = -(PATH_NODE_CARD_HEIGHT + PATH_NODE_CARD_MARGIN_BOTTOM)
export const PATH_NODE_CARD_LEFT_OFFSET = 0 - NODE_BORDER_RADIUS

/** Space between two nodes, should fit the node label and it's vertical margins. */
const NODE_PADDING = PATH_NODE_CARD_MARGIN_TOP + PATH_NODE_CARD_HEIGHT + PATH_NODE_CARD_MARGIN_BOTTOM

const createCanvas = (canvasRef: RefObject<HTMLDivElement>, width: number, height: number): D3Selector => {
    return d3
        .select(canvasRef.current)
        .append('svg')
        .classed('Paths__canvas', true)
        .style('background', 'var(--item-background)')
        .style('width', `${width}px`)
        .style('height', `${height}px`)
}

const createSankeyGenerator = (width: number, height: number): Sankey.SankeyLayout<any, any, any> => {
    /** **Left canvas margin**
     * - Expanded by the border radius to make sure the nodes are not cut off.
     */
    const marginLeft = 0 + NODE_BORDER_RADIUS

    /** **Top canvas margin**
     * - Expanded by the node label height and it's bottom margin, so that the
     * first label fits into the canvas.
     */
    const marginTop = PATH_NODE_CARD_HEIGHT + PATH_NODE_CARD_MARGIN_BOTTOM

    /** **Right canvas margin**
     * - Expanded by the border radius to make sure the nodes are not cut off.
     * - Expanded by the width of the node label, minus the already existing
     * node width to make sure the node label fits into the canvas.
     */
    const marginRight = 0 + NODE_BORDER_RADIUS + PATH_NODE_CARD_WIDTH - NODE_WIDTH

    /** **Bottom canvas margin** */
    const marginBottom = 0

    // @ts-expect-error - d3 sankey typing things
    return new Sankey.sankey()
        .nodeId((d: PathNodeData) => d.name)
        .nodeAlign(Sankey.sankeyLeft)
        .nodeSort(null)
        .nodeWidth(NODE_WIDTH)
        .nodePadding(NODE_PADDING)
        .size([width, height])
        .extent([
            [marginLeft, marginTop], // top-left coordinates
            [width - marginRight, height - marginBottom], // bottom-right coordinates
        ])
}

const appendPathNodes = (
    svg: any,
    nodes: PathNodeData[],
    pathsFilter: PathsFilter,
    funnelPathsFilter: FunnelPathsFilter
): void => {
    svg.append('g')
        .selectAll('rect')
        .data(nodes)
        .join('rect')
        .attr('x', (d: PathNodeData) => d.x0 - NODE_BORDER_RADIUS)
        .attr('y', (d: PathNodeData) => d.y0)
        .attr('rx', NODE_BORDER_RADIUS)
        .attr('height', (d: PathNodeData) => d.y1 - d.y0)
        .attr('width', (d: PathNodeData) => d.x1 - d.x0 + 2 * NODE_BORDER_RADIUS)
        .attr('fill', (d: PathNodeData) => {
            let c
            for (const link of d.sourceLinks) {
                if (c === undefined) {
                    c = link.color
                } else if (c !== link.color) {
                    c = null
                }
            }
            if (c === undefined) {
                for (const link of d.targetLinks) {
                    if (c === undefined) {
                        c = link.color
                    } else if (c !== link.color) {
                        c = null
                    }
                }
            }
            if (isSelectedPathStartOrEnd(pathsFilter, funnelPathsFilter, d)) {
                return 'var(--paths-node-start-or-end)'
            }
            const startNodeColor = c && d3.color(c) ? d3.color(c) : 'var(--paths-node)'
            return startNodeColor
        })
        .append('title')
        .text((d: PathNodeData) => `${stripHTTP(d.name)}\n${d.value.toLocaleString()}`)
}

const appendPathLinks = (svg: any, links: PathNodeData[]): void => {
    const link = svg
        .append('g')
        .attr('fill', 'none')
        .selectAll('g')
        .data(links)
        .join('g')
        .attr('stroke', 'var(--paths-link)')
        .attr('opacity', 0.1)

    link.append('path')
        .attr('d', Sankey.sankeyLinkHorizontal())
        .attr('id', (d: PathNodeData) => `path-${d.index}`)
        .attr('stroke-width', (d: PathNodeData) => {
            return Math.max(1, d.width)
        })
        .on('mouseover', (_event: MouseEvent, data: PathNodeData) => {
            svg.select(`#path-${data.index}`).attr('stroke', 'var(--paths-link-hover)')
            if (data?.source?.targetLinks.length === 0) {
                return
            }
            const nodesToColor = [data.source]
            const pathCardsToShow: number[] = []
            while (nodesToColor.length > 0) {
                const _node = nodesToColor.pop()
                _node?.targetLinks.forEach((_link: PathTargetLink) => {
                    svg.select(`#path-${_link.index}`).attr('stroke', 'var(--paths-link-hover)')
                    nodesToColor.push(_link.source)
                    pathCardsToShow.push(_link.source.index)
                })
            }
            const pathCards = [data.target]
            pathCardsToShow.push(data.target.index, data.source.index)
            while (pathCards.length > 0) {
                const node = pathCards.pop()
                node?.sourceLinks.forEach((l: PathTargetLink) => {
                    pathCards.push(l.target)
                    pathCardsToShow.push(l.target.index)
                })
            }
        })
        .on('mouseleave', () => {
            svg.selectAll('path').attr('stroke', 'var(--paths-link)')
        })
}

export function renderPaths(
    canvasRef: RefObject<HTMLDivElement>,
    _canvasWidth: number | undefined,
    _canvasHeight: number | undefined,
    paths: Paths,
    pathsFilter: PathsFilter,
    funnelPathsFilter: FunnelPathsFilter,
    setNodes: Dispatch<SetStateAction<PathNodeData[]>>
): void {
    const canvasWidth = _canvasWidth || FALLBACK_CANVAS_WIDTH
    const canvasHeight = _canvasHeight || FALLBACK_CANVAS_HEIGHT

    if (!paths || paths.nodes.length === 0) {
        return
    }

    const maxLayer = paths.links.reduce((prev, curr) => {
        return Math.max(prev, Number(curr.target.match(/[^_]*/)))
    }, 0)

    const minWidth = canvasWidth > FALLBACK_CANVAS_WIDTH || maxLayer < 3 ? canvasWidth : FALLBACK_CANVAS_WIDTH

    const width = maxLayer > 5 && canvasWidth ? (minWidth / 5) * maxLayer : minWidth
    const height = canvasHeight

    const svg = createCanvas(canvasRef, width, height)
    const sankey = createSankeyGenerator(width, height)

    // :TRICKY: clone the paths, as d3 mutates data in place.
    const clonedPaths = structuredClone(paths)
    const { nodes, links } = sankey(clonedPaths)

    appendPathLinks(svg, links)
    appendPathNodes(svg, nodes, pathsFilter, funnelPathsFilter)

    // :TRICKY: this needs to come last, as d3 mutates data in place and otherwise
    // we won't have node positions.
    setNodes(nodes)
}
