import { Dispatch, RefObject, SetStateAction } from 'react'
import * as d3 from 'd3'
import * as Sankey from 'd3-sankey'

import { PathsFilterType } from '~/types'
import { stripHTTP } from 'lib/utils'
import { D3Selector } from 'lib/hooks/useD3'

import { HIDE_PATH_CARD_HEIGHT, FALLBACK_CANVAS_WIDTH } from './Paths'
import { roundedRect, isSelectedPathStartOrEnd, PathNodeData, PathTargetLink } from './pathUtils'
import { PathNode } from './pathsLogic'

const createCanvas = (canvasRef: RefObject<HTMLDivElement>, width: number, height: number): D3Selector => {
    return d3
        .select(canvasRef.current)
        .append('svg')
        .style('background', 'var(--item-background)')
        .style('width', width)
        .style('height', height)
}

const createSankey = (width: number, height: number): Sankey.SankeyLayout<any, any, any> => {
    // @ts-expect-error - d3 sankey typing things
    return new Sankey.sankey()
        .nodeId((d: PathNodeData) => d.name)
        .nodeAlign(Sankey.sankeyJustify)
        .nodeSort(null)
        .nodeWidth(15)
        .size([width, height])
}

const appendPathNodes = (
    svg: any,
    nodes: PathNodeData[],
    filter: Partial<PathsFilterType>,
    setPathItemCards: Dispatch<SetStateAction<PathNodeData[]>>
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
            if (isSelectedPathStartOrEnd(filter, d)) {
                return d3.color('purple')
            }
            const startNodeColor = c && d3.color(c) ? d3.color(c) : d3.color('#5375ff')
            return startNodeColor
        })
        .on('mouseover', (data: PathNodeData) => {
            if (data.y1 - data.y0 > HIDE_PATH_CARD_HEIGHT) {
                return
            }
            setPathItemCards(
                nodes.map((node: PathNodeData) =>
                    node.index === data.index
                        ? { ...node, visible: true }
                        : { ...node, visible: node.y1 - node.y0 > HIDE_PATH_CARD_HEIGHT }
                )
            )
        })
        .append('title')
        .text((d: PathNodeData) => `${stripHTTP(d.name)}\n${d.value.toLocaleString()}`)
}

const appendDropoffs = (svg: D3Selector): void => {
    const dropOffGradient = svg
        .append('defs')
        .append('linearGradient')
        .attr('id', 'dropoff-gradient')
        .attr('gradientTransform', 'rotate(90)')

    dropOffGradient.append('stop').attr('offset', '0%').attr('stop-color', 'rgba(220,53,69,0.7)')

    dropOffGradient.append('stop').attr('offset', '100%').attr('stop-color', '#fff')
}

const appendPathLinks = (
    svg: any,
    links: PathNodeData[],
    nodes: PathNodeData[],
    setPathItemCards: Dispatch<SetStateAction<PathNodeData[]>>
): void => {
    const link = svg
        .append('g')
        .attr('fill', 'none')
        .selectAll('g')
        .data(links)
        .join('g')
        .attr('stroke', 'var(--primary)')
        .attr('opacity', 0.35)

    link.append('path')
        .attr('d', Sankey.sankeyLinkHorizontal())
        .attr('id', (d: PathNodeData) => `path-${d.index}`)
        .attr('stroke-width', (d: PathNodeData) => {
            return Math.max(1, d.width)
        })
        .on('mouseover', (data: PathNodeData) => {
            svg.select(`#path-${data.index}`).attr('stroke', 'blue')
            if (data?.source?.targetLinks.length === 0) {
                return
            }
            const nodesToColor = [data.source]
            const pathCardsToShow: number[] = []
            while (nodesToColor.length > 0) {
                const _node = nodesToColor.pop()
                _node?.targetLinks.forEach((_link: PathTargetLink) => {
                    svg.select(`#path-${_link.index}`).attr('stroke', 'blue')
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
            setPathItemCards(
                nodes.map((node: PathNodeData) => ({
                    ...node,
                    ...{
                        visible: pathCardsToShow.includes(node.index)
                            ? true
                            : node.y1 - node.y0 > HIDE_PATH_CARD_HEIGHT,
                    },
                }))
            )
        })
        .on('mouseleave', () => {
            svg.selectAll('path').attr('stroke', 'var(--primary)')
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

const addChartAxisLines = (svg: D3Selector, height: number, nodes: PathNodeData[], maxLayer: number): void => {
    if (maxLayer > 5) {
        const arr = [...Array(maxLayer)]
        const minWidthApart = nodes[1].x0 - nodes[0].x0
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
    paths: { links: PathNode[]; nodes: any[] },
    filter: Partial<PathsFilterType>,
    setPathItemCards: Dispatch<SetStateAction<PathNodeData[]>>
): void {
    if (!paths || paths.nodes.length === 0) {
        return
    }

    const maxLayer = paths.links.reduce((prev, curr) => {
        // @ts-expect-error - sometimes target is an object instead of string
        const currNum = curr.target.name || curr.target
        return Math.max(prev, Number(currNum.match(/[^_]*/)))
    }, 0)

    const minWidth = canvasWidth > FALLBACK_CANVAS_WIDTH || maxLayer < 3 ? canvasWidth : FALLBACK_CANVAS_WIDTH

    const width = maxLayer > 5 && canvasWidth ? (minWidth / 5) * maxLayer : minWidth
    const height = canvasHeight

    const svg = createCanvas(canvasRef, width, height)
    const sankey = createSankey(width, height)
    const { nodes, links } = sankey({
        nodes: paths.nodes.map((d) => ({ ...d })),
        links: paths.links.map((d) => ({ ...d })),
    })

    setPathItemCards(
        nodes.map((node: PathNodeData) => ({ ...node, visible: node.y1 - node.y0 > HIDE_PATH_CARD_HEIGHT }))
    )

    appendPathNodes(svg, nodes, filter, setPathItemCards)
    appendDropoffs(svg)
    appendPathLinks(svg, links, nodes, setPathItemCards)
    addChartAxisLines(svg, height, nodes, maxLayer)
}
