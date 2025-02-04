import * as d3 from 'd3'
import * as Sankey from 'd3-sankey'
import { stripHTTP } from 'lib/utils'
import { Dispatch, RefObject, SetStateAction } from 'react'

import { FunnelPathsFilter, PathsFilter, PathsLink } from '~/queries/schema'

import { FALLBACK_CANVAS_WIDTH, HIDE_PATH_CARD_HEIGHT } from './Paths'
import { isSelectedPathStartOrEnd, roundedRect } from './pathUtils'

export type PathsData = {
    links: PathsLink[]
    nodes: PathNodeExtra[]
}

export type PathNodeExtra = { name: string }
type PathsLinkExtra = { average_conversion_time: number }

export type D3PathsNode = Sankey.SankeyNode<PathNodeExtra, PathsLinkExtra>
type D3PathsLink = Sankey.SankeyLink<PathNodeExtra, PathsLinkExtra>
type D3SelectorSvg = d3.Selection<SVGSVGElement, unknown, null, undefined>

interface InitializedD3Node extends D3PathsNode {
    sourceLinks: Array<Sankey.SankeyLink<PathNodeExtra, PathsLinkExtra>>
    targetLinks: Array<Sankey.SankeyLink<PathNodeExtra, PathsLinkExtra>>
}

interface InitializedD3PathsLink extends D3PathsLink {
    source: InitializedD3Node
    target: InitializedD3Node
}

const isInitializedPathsLink = (d: D3PathsLink): d is InitializedD3PathsLink => {
    return typeof d.source === 'object' && d.source !== null && 'value' in d.source
}

const createCanvas = (canvasRef: RefObject<HTMLDivElement>, width: number, height: number): D3SelectorSvg => {
    return d3
        .select(canvasRef.current)
        .append('svg')
        .classed('Paths__canvas', true)
        .style('background', 'var(--item-background)')
        .style('width', `${width}px`)
        .style('height', `${height}px`)
}

const createSankey = (
    width: number,
    height: number
): Sankey.SankeyLayout<Sankey.SankeyGraph<PathNodeExtra, PathsLink>, PathNodeExtra, PathsLink> => {
    return Sankey.sankey<PathsData, PathNodeExtra, PathsLink>()
        .nodeId((d) => d.name)
        .nodeAlign(Sankey.sankeyJustify)
        .nodeWidth(15)
        .size([width, height])
}

const appendPathNodes = (
    svg: D3SelectorSvg,
    nodes: D3PathsNode[],
    pathsFilter: PathsFilter,
    funnelPathsFilter: FunnelPathsFilter,
    setNodeCards: Dispatch<SetStateAction<D3PathsNode[]>>
): void => {
    svg.append('g')
        .selectAll('rect')
        .data(nodes)
        .join('rect')
        .attr('x', (d) => d.x0! + 1)
        .attr('y', (d) => d.y0!)
        .attr('height', (d) => d.y1! - d.y0!)
        .attr('width', (d) => d.x1! - d.x0! - 2)
        .attr('fill', (d) => {
            let c
            for (const link of d.sourceLinks!) {
                if (c === undefined) {
                    c = link.color
                } else if (c !== link.color) {
                    c = null
                }
            }
            if (c === undefined) {
                for (const link of d.targetLinks!) {
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
        .on('mouseover', (_event, data) => {
            if (data.y1! - data.y0! > HIDE_PATH_CARD_HEIGHT) {
                return
            }
            setNodeCards(
                nodes.map((node) =>
                    node.index === data.index
                        ? { ...node, visible: true }
                        : { ...node, visible: node.y1! - node.y0! > HIDE_PATH_CARD_HEIGHT }
                )
            )
        })
        .append('title')
        .text((d) => `${stripHTTP(d.name)}\n${d.value.toLocaleString()}`)
}

const appendDropoffs = (svg: D3SelectorSvg): void => {
    const dropOffGradient = svg
        .append('defs')
        .append('linearGradient')
        .attr('id', 'dropoff-gradient')
        .attr('gradientTransform', 'rotate(90)')

    dropOffGradient.append('stop').attr('offset', '0%').attr('stop-color', 'var(--paths-dropoff)')

    dropOffGradient.append('stop').attr('offset', '100%').attr('stop-color', 'var(--bg-light)')
}

const appendPathLinks = (
    svg: D3SelectorSvg,
    links: D3PathsLink[],
    nodes: D3PathsNode[],
    setNodeCards: Dispatch<SetStateAction<D3PathsNode[]>>
): void => {
    const link = svg
        .append('g')
        .attr('fill', 'none')
        .selectAll('g')
        .data(links)
        .join('g')
        .attr('stroke', 'var(--paths-link)')
        .attr('opacity', 0.35)

    link.append('path')
        .attr('d', Sankey.sankeyLinkHorizontal())
        .attr('id', (d) => `path-${d.index}`)
        .attr('stroke-width', (d) => {
            return Math.max(1, d.width!)
        })
        .on('mouseover', (_event, data) => {
            svg.select(`#path-${data.index}`).attr('stroke', 'var(--paths-link-hover)')
            if (!isInitializedPathsLink(data) || data.source?.targetLinks.length === 0) {
                return
            }
            const nodesToColor = [data.source]
            const pathCardsToShow: number[] = []
            while (nodesToColor.length > 0) {
                const _node = nodesToColor.pop()
                _node?.targetLinks.forEach((_link) => {
                    svg.select(`#path-${_link.index}`).attr('stroke', 'var(--paths-link-hover)')
                    nodesToColor.push(_link.source)
                    pathCardsToShow.push(_link.source.index)
                })
            }
            const pathCards = [data.target]
            pathCardsToShow.push(data.target.index, data.source.index)
            while (pathCards.length > 0) {
                const node = pathCards.pop()
                node?.sourceLinks.forEach((l) => {
                    pathCards.push(l.target)
                    pathCardsToShow.push(l.target.index)
                })
            }
            setNodeCards(
                nodes.map((node) => ({
                    ...node,
                    ...{
                        visible: pathCardsToShow.includes(node.index!)
                            ? true
                            : node.y1! - node.y0! > HIDE_PATH_CARD_HEIGHT,
                    },
                }))
            )
        })
        .on('mouseleave', () => {
            svg.selectAll('path').attr('stroke', 'var(--paths-link)')
        })

    link.append('g')
        .append('path')
        .attr('d', (data) => {
            if (!isInitializedPathsLink(data) || data.source.layer === 0) {
                return null
            }
            const _height =
                data.source.y1 - data.source.y0 - data.source.sourceLinks.reduce((prev, curr) => prev + curr.width, 0)
            return roundedRect(0, 0, 30, _height, Math.min(25, _height), false, true, false, false)
        })
        .attr('fill', 'url(#dropoff-gradient)')
        .attr('stroke-width', 0)
        .attr('transform', (data) => {
            return (
                'translate(' +
                Math.round(data.source.x1) +
                ',' +
                Math.round(data.source.y0 + data.source.sourceLinks.reduce((prev, curr) => prev + curr.width, 0)) +
                ')'
            )
        })
}

const addChartAxisLines = (svg: D3SelectorSvg, height: number, nodes: D3PathsNode[], maxLayer: number): void => {
    if (maxLayer > 5) {
        const arr = [...Array(maxLayer)]
        const minWidthApart = nodes[1].x0! - nodes[0].x0!
        arr.forEach((_, i) => {
            svg.append('line')
                .style('stroke', 'var(--border)')
                .attr('stroke-width', 2)
                .attr('x1', minWidthApart * (i + 1) - 20)
                .attr('y1', 0)
                .attr('x2', minWidthApart * (i + 1) - 20)
                .attr('y2', height)
        })
    }
}

export function renderPaths(
    canvasRef: RefObject<HTMLDivElement>,
    canvasWidth: number,
    canvasHeight: number,
    paths: PathsData,
    pathsFilter: PathsFilter,
    funnelPathsFilter: FunnelPathsFilter,
    setNodeCards: Dispatch<SetStateAction<D3PathsNode[]>>
): void {
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
    const sankey = createSankey(width, height)
    const { nodes, links } = sankey(paths)

    setNodeCards(nodes.map((node) => ({ ...node, visible: node.y1! - node.y0! > HIDE_PATH_CARD_HEIGHT })))

    appendPathNodes(svg, nodes, pathsFilter, funnelPathsFilter, setNodeCards)
    appendDropoffs(svg)
    appendPathLinks(svg, links, nodes, setNodeCards)
    addChartAxisLines(svg, height, nodes, maxLayer)
}
