import * as d3 from 'd3'
import * as Sankey from 'd3-sankey'
import { D3Selector } from 'lib/hooks/useD3'
import { stripHTTP } from 'lib/utils'
import { Dispatch, RefObject, SetStateAction } from 'react'

import { FunnelPathsFilter, PathsFilter } from '~/queries/schema'

import { FALLBACK_CANVAS_WIDTH, HIDE_PATH_CARD_HEIGHT } from './PathsV2'
import { isSelectedPathStartOrEnd, PathNodeData, PathTargetLink, roundedRect } from './pathUtils'
import { Paths } from './types'

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
    // @ts-expect-error - d3 sankey typing things
    return new Sankey.sankey()
        .nodeId((d: PathNodeData) => d.name)
        .nodeAlign(Sankey.sankeyLeft)
        .nodeSort(null)
        .nodeWidth(15)
        .size([width, height])
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
        .attr('x', (d: PathNodeData) => d.x0 + 1)
        .attr('y', (d: PathNodeData) => d.y0)
        .attr('height', (d: PathNodeData) => d.y1 - d.y0)
        .attr('width', (d: PathNodeData) => d.x1 - d.x0 - 2)
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
        .on('mouseover', (_event: MouseEvent, data: PathNodeData) => {
            if (data.y1 - data.y0 > HIDE_PATH_CARD_HEIGHT) {
                return
            }
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

    link.append('g')
        .append('path')
        .attr('d', (data: PathNodeData) => {
            if (data.source.layer === 0) {
                return
            }
            const _height =
                data.source.y1 - data.source.y0 - data.source.sourceLinks.reduce((prev, curr) => prev + curr.width, 0)
            return roundedRect(0, 0, 30, _height, Math.min(25, _height), false, true, false, false)
        })
        .attr('fill', 'url(#dropoff-gradient)')
        .attr('stroke-width', 0)
        .attr('transform', (data: PathNodeData) => {
            return (
                'translate(' +
                Math.round(data.source.x1) +
                ',' +
                Math.round(data.source.y0 + data.source.sourceLinks.reduce((prev, curr) => prev + curr.width, 0)) +
                ')'
            )
        })
}

export function renderPaths(
    canvasRef: RefObject<HTMLDivElement>,
    canvasWidth: number,
    canvasHeight: number,
    paths: Paths,
    pathsFilter: PathsFilter,
    funnelPathsFilter: FunnelPathsFilter,
    setNodes: Dispatch<SetStateAction<PathNodeData[]>>
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
    const sankey = createSankeyGenerator(width, height)

    // :TRICKY: clone the paths, as d3 mutates data in place
    const clonedPaths = structuredClone(paths)
    const { nodes, links } = sankey(clonedPaths)

    appendPathNodes(svg, nodes, pathsFilter, funnelPathsFilter)
    appendPathLinks(svg, links)

    // :TRICKY: this needs to come last, as d3 mutates data in place and otherwise
    // we won't have node positions.
    setNodes(nodes)
}
