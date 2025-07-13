import * as d3 from 'd3'
import * as Sankey from 'd3-sankey'
import { Dispatch, RefObject, SetStateAction } from 'react'

import { D3Selector } from 'lib/hooks/useD3'

import { FunnelPathsFilter, PathsFilter } from '~/queries/schema/schema-general'

import { PathNodeData, PathTargetLink, isSelectedPathStartOrEnd } from './pathUtils'
import { Paths } from './types'

/*
 * Canvas
 */

const FALLBACK_CANVAS_WIDTH = 1000
const FALLBACK_CANVAS_HEIGHT = 0
const CANVAS_PADDING_HORIZONTAL = 12
const CANVAS_PADDING_VERTICAL = 12

/*
 * Node
 */

// We want the border radius to overlap the links. For this we subtract the border radius of both
// sides from the node width, and add it back to the svg element that is moved left by the border radius.
//
// We also expand the canvas margin by the border radius on both sides to make sure the nodes are not cut off.
const NODE_BORDER_RADIUS = 4
const NODE_WIDTH = 48 - 2 * NODE_BORDER_RADIUS
const NODE_MIN_HEIGHT = 3

/*
 * Node label
 */

export const NODE_LABEL_WIDTH = 240
export const NODE_LABEL_HEIGHT = 44
const NODE_LABEL_MARGIN_TOP = 20
const NODE_LABEL_MARGIN_BOTTOM = 10
export const NODE_LABEL_TOP_OFFSET = -(NODE_LABEL_HEIGHT + NODE_LABEL_MARGIN_BOTTOM)
export const NODE_LABEL_LEFT_OFFSET = 0 - NODE_BORDER_RADIUS

/** Space between two nodes, should fit the node label and it's vertical margins. */
const NODE_PADDING = NODE_LABEL_MARGIN_TOP + NODE_LABEL_HEIGHT + NODE_LABEL_MARGIN_BOTTOM

/*
 * Node links
 */
const LINK_OPACITY = 0.1
const LINK_OPACITY_EMPHASIZED = 0.25
const LINK_OPACITY_DEEMPHASIZED = 0.05

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
    const marginLeft = CANVAS_PADDING_HORIZONTAL + NODE_BORDER_RADIUS

    /** **Top canvas margin**
     * - Expanded by the node label height and it's bottom margin, so that the
     * first label fits into the canvas.
     */
    const marginTop = NODE_LABEL_HEIGHT + NODE_LABEL_MARGIN_BOTTOM + CANVAS_PADDING_VERTICAL

    /** **Right canvas margin**
     * - Expanded by the border radius to make sure the nodes are not cut off.
     * - Expanded by the width of the node label, minus the already existing
     * node width to make sure the node label fits into the canvas.
     */
    const marginRight = CANVAS_PADDING_HORIZONTAL + NODE_BORDER_RADIUS + NODE_LABEL_WIDTH - NODE_WIDTH

    /** **Bottom canvas margin** */
    const marginBottom = CANVAS_PADDING_VERTICAL

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

const appendNodes = (
    svg: any,
    nodes: PathNodeData[],
    pathsFilter: PathsFilter,
    funnelPathsFilter: FunnelPathsFilter,
    openPersonsModal: (props: { path_dropoff_key?: string; path_end_key?: string; path_start_key?: string }) => void
): void => {
    svg.append('g')
        .selectAll('rect')
        .data(nodes)
        .join('rect')
        .attr('x', (node: PathNodeData) => node.x0 - NODE_BORDER_RADIUS)
        .attr('y', (node: PathNodeData) => node.y0)
        .attr('rx', NODE_BORDER_RADIUS)
        .attr('height', (node: PathNodeData) => Math.max(node.y1 - node.y0, NODE_MIN_HEIGHT))
        .attr('width', (node: PathNodeData) => node.x1 - node.x0 + 2 * NODE_BORDER_RADIUS)
        .attr('fill', (node: PathNodeData) => {
            if (isSelectedPathStartOrEnd(pathsFilter, funnelPathsFilter, node)) {
                return 'var(--paths-node-start-or-end)'
            }
            return 'var(--paths-node)'
        })
        .attr('id', (node: PathNodeData) => `node-${node.index}`)
        .on('click', (_event: MouseEvent, node: PathNodeData) => {
            openPersonsModal({ path_end_key: node.name })
        })
        .style('cursor', 'pointer')
        .on('mouseover', (_event: MouseEvent, node: PathNodeData) => {
            svg.selectAll('path').attr('opacity', LINK_OPACITY_DEEMPHASIZED)

            // apply effect to hovered node
            const isStartOrEndNode = isSelectedPathStartOrEnd(pathsFilter, funnelPathsFilter, node)
            const nodeColor = isStartOrEndNode ? 'var(--paths-node-start-or-end-hover)' : 'var(--paths-node-hover)'
            svg.select(`#node-${node.index}`).attr('fill', nodeColor)

            // recursively apply effect to incoming links
            const sourceNodes = [node]
            while (sourceNodes.length > 0) {
                const _node = sourceNodes.pop()
                _node?.targetLinks.forEach((link: PathTargetLink) => {
                    svg.select(`#link-${link.index}`).attr('opacity', LINK_OPACITY_EMPHASIZED)
                    sourceNodes.push(link.source) // add source node to recursion
                })
            }

            // recursively apply effect to outgoing links
            const targetNodes = [node]
            while (targetNodes.length > 0) {
                const node = targetNodes.pop()
                node?.sourceLinks.forEach((link: PathTargetLink) => {
                    svg.select(`#link-${link.index}`).attr('opacity', LINK_OPACITY_EMPHASIZED)
                    targetNodes.push(link.target) // add target node to recursion
                })
            }
        })
        .on('mouseleave', (_event: MouseEvent, node: PathNodeData) => {
            // reset hovered node
            const isStartOrEndNode = isSelectedPathStartOrEnd(pathsFilter, funnelPathsFilter, node)
            const nodeColor = isStartOrEndNode ? 'var(--paths-node-start-or-end)' : 'var(--paths-node)'
            svg.select(`#node-${node.index}`).attr('fill', nodeColor)

            // reset all links
            svg.selectAll('path').attr('opacity', LINK_OPACITY)
        })
}

const appendLinks = (svg: any, links: PathNodeData[]): void => {
    svg.selectAll('path')
        .data(links)
        .join('path')
        .attr('d', Sankey.sankeyLinkHorizontal())
        .attr('id', (link: PathNodeData) => `link-${link.index}`)
        .attr('fill', 'none')
        .attr('stroke', 'var(--paths-link)')
        .attr('stroke-width', (link: PathNodeData) => Math.max(1, link.width))
        .attr('opacity', LINK_OPACITY)
        .on('mouseover', (_event: MouseEvent, link: PathNodeData) => {
            // apply effect to hovered link
            svg.select(`#link-${link.index}`).attr('opacity', LINK_OPACITY_EMPHASIZED)
        })
        .on('mouseleave', (_event: MouseEvent, link: PathNodeData) => {
            // reset hovered link
            svg.select(`#link-${link.index}`).attr('opacity', LINK_OPACITY)
        })
}

export function renderPaths(
    canvasRef: RefObject<HTMLDivElement>,
    _canvasWidth: number | undefined,
    _canvasHeight: number | undefined,
    paths: Paths,
    pathsFilter: PathsFilter,
    funnelPathsFilter: FunnelPathsFilter,
    setNodes: Dispatch<SetStateAction<PathNodeData[]>>,
    openPersonsModal: (props: { path_dropoff_key?: string; path_end_key?: string; path_start_key?: string }) => void
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

    appendLinks(svg, links)
    appendNodes(svg, nodes, pathsFilter, funnelPathsFilter, openPersonsModal)

    // :TRICKY: this needs to come last, as d3 mutates data in place and otherwise
    // we won't have node positions.
    setNodes(nodes)
}
