import * as d3 from 'd3'
import * as Sankey from 'd3-sankey'
import { D3Selector } from 'lib/hooks/useD3'
import { stripHTTP } from 'lib/utils'
import { Dispatch, RefObject, SetStateAction } from 'react'

import { FunnelPathsFilter, PathsFilter } from '~/queries/schema'

import { DATA_LINKS, DATA_NODES } from './dummyData'
import { FALLBACK_CANVAS_WIDTH, HIDE_PATH_CARD_HEIGHT } from './Paths'
import { isSelectedPathStartOrEnd, PathNodeData, PathTargetLink, roundedRect } from './pathUtils'
import { Paths } from './types'

export const NODE_WIDTH = 48
export const NODE_BORDER_RADIUS = 2
export const NODE_PADDING = 64

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
    const marginLeft = 0 + NODE_BORDER_RADIUS + 10,
        marginTop = 0 + 48,
        marginRight = 0 + NODE_BORDER_RADIUS + 10,
        marginBottom = 0 + 48
    // @ts-expect-error - d3 sankey typing things
    return new Sankey.sankey()
        .nodeId((d: PathNodeData) => d.name)
        .nodeAlign(Sankey.sankeyCenter)
        .nodeSort(null)
        .linkSort(null)
        .nodeWidth(NODE_WIDTH - 2 * NODE_BORDER_RADIUS)
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
    funnelPathsFilter: FunnelPathsFilter,
    setNodeCards: Dispatch<SetStateAction<PathNodeData[]>>
): void => {
    svg.append('g')
        .selectAll('rect')
        .data(nodes)
        .join('rect')
        .attr('x', (d: PathNodeData) => d.x0 - NODE_BORDER_RADIUS)
        .attr('y', (d: PathNodeData) => d.y0 - 0.5 * NODE_BORDER_RADIUS)
        .attr('rx', NODE_BORDER_RADIUS)
        .attr('height', (d: PathNodeData) => Math.max(d.y1 - d.y0, 4))
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
        .on('mouseover', (_event: MouseEvent, data: PathNodeData) => {
            if (data.y1 - data.y0 > HIDE_PATH_CARD_HEIGHT) {
                return
            }
            // setNodeCards(
            //     nodes.map((node: PathNodeData) =>
            //         node.index === data.index
            //             ? { ...node, visible: true }
            //             : { ...node, visible: node.y1 - node.y0 > HIDE_PATH_CARD_HEIGHT }
            //     )
            // )
            setNodeCards(nodes.map((node: PathNodeData) => ({ ...node, visible: true })))
        })
        .append('title')
        .text((d: PathNodeData) => `${stripHTTP(d.name)}\n${d.value.toLocaleString()}`)
}

// const appendDropoffs = (svg: D3Selector): void => {
//     const dropOffGradient = svg
//         .append('defs')
//         .append('linearGradient')
//         .attr('id', 'dropoff-gradient')
//         .attr('gradientTransform', 'rotate(90)')

//     dropOffGradient.append('stop').attr('offset', '0%').attr('stop-color', 'var(--paths-dropoff)')

//     dropOffGradient.append('stop').attr('offset', '100%').attr('stop-color', 'var(--bg-light)')
// }

const appendPathLinks = (
    svg: any,
    links: PathNodeData[],
    nodes: PathNodeData[],
    setNodeCards: Dispatch<SetStateAction<PathNodeData[]>>
): void => {
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
            // setNodeCards(
            //     nodes.map((node: PathNodeData) => ({
            //         ...node,
            //         ...{
            //             visible: pathCardsToShow.includes(node.index)
            //                 ? true
            //                 : node.y1 - node.y0 > HIDE_PATH_CARD_HEIGHT,
            //         },
            //     }))
            // )
            setNodeCards(
                nodes.map((node: PathNodeData) => ({
                    ...node,
                    visible: true,
                    // ...{
                    //     visible: pathCardsToShow.includes(node.index)
                    //         ? true
                    //         : node.y1 - node.y0 > HIDE_PATH_CARD_HEIGHT,
                    // },
                }))
            )
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

// const addChartAxisLines = (svg: D3Selector, height: number, nodes: PathNodeData[], maxLayer: number): void => {
//     if (maxLayer > 5) {
//         const arr = [...Array(maxLayer)]
//         const minWidthApart = nodes[1].x0 - nodes[0].x0
//         arr.forEach((_, i) => {
//             svg.append('line')
//                 .style('stroke', 'var(--border)')
//                 .attr('stroke-width', 2)
//                 .attr('x1', minWidthApart * (i + 1) - 20)
//                 .attr('y1', 0)
//                 .attr('x2', minWidthApart * (i + 1) - 20)
//                 .attr('y2', height)
//         })
//     }
// }

const processPaths = ({ nodes, links }: Paths): Paths => {
    return { nodes, links }

    const totals = links.reduce((acc, { source, value }) => {
        const key = source.split('_')[0]
        acc[key] = (acc[key] || 0) + value
        return acc
    }, {})

    console.log(totals)

    return {
        nodes,
        links: links.map((link) => {
            const key = link.source.split('_')[0]
            return { ...link, value: link.value / totals[key] }
        }),
    }
}

export function renderPaths(
    canvasRef: RefObject<HTMLDivElement>,
    canvasWidth: number,
    canvasHeight: number,
    paths: Paths,
    pathsFilter: PathsFilter,
    funnelPathsFilter: FunnelPathsFilter,
    setNodeCards: Dispatch<SetStateAction<PathNodeData[]>>
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

    const dataPaths = { nodes: DATA_NODES, links: DATA_LINKS }

    // clone the paths, as sankey mutates the data
    // const clonedPaths = structuredClone(dataPaths)
    const clonedPaths = structuredClone(paths)
    console.debug('paths', dataPaths)
    const { nodes: _nodes, links } = sankey(processPaths(clonedPaths))

    console.debug('_nodes', _nodes)
    const nodes = _nodes.map((node: any) => node)

    // setNodeCards(nodes.map((node: PathNodeData) => ({ ...node, visible: node.y1 - node.y0 > HIDE_PATH_CARD_HEIGHT })))
    setNodeCards(nodes.map((node: PathNodeData) => ({ ...node, visible: true })))
    appendPathLinks(svg, links, nodes, setNodeCards)
    // appendDropoffs(svg)
    appendPathNodes(svg, nodes, pathsFilter, funnelPathsFilter, setNodeCards)

    // addChartAxisLines(svg, height, nodes, maxLayer)
}
