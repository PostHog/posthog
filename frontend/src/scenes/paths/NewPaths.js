import React, { useRef, useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { copyToClipboard, stripHTTP } from 'lib/utils'
import * as d3 from 'd3'
import * as Sankey from 'd3-sankey'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { Button, Menu, Dropdown, Tooltip, Row } from 'antd'
import { PathsCompletedArrow, PathsDropoffArrow } from 'lib/components/icons'
import { ClockCircleOutlined } from '@ant-design/icons'
import { humanFriendlyDuration } from 'lib/utils'
import './Paths.scss'
import { ValueInspectorButton } from 'scenes/funnels/FunnelBarGraph'
import { FunnelPathType } from '~/types'
import { roundedRect, pageUrl } from './pathUtils'
import { insightLogic } from 'scenes/insights/insightLogic'

function NoData() {
    return (
        <div style={{ padding: '1rem' }}>
            We don't have enough data to show anything here. You might need to send us some frontend (JS) events, as we
            use the <pre style={{ display: 'inline' }}>$current_url</pre> property to calculate paths.
        </div>
    )
}

const DEFAULT_PATHS_ID = 'default_paths'
const HIDE_PATH_CARD_HEIGHT = 30

export function NewPaths({ dashboardItemId = null, color = 'white' }) {
    const canvas = useRef(null)
    const size = useWindowSize()
    const { insightProps } = useValues(insightLogic)
    const { paths, resultsLoading: pathsLoading, filter } = useValues(pathsLogic(insightProps))
    const { openPersonsModal, setFilter, updateExclusions, viewPathToFunnel } = useActions(pathsLogic(insightProps))
    const [pathItemCards, setPathItemCards] = useState([])
    useEffect(() => {
        setPathItemCards([])
        renderPaths()
    }, [paths, !pathsLoading, size, color])

    const createCanvas = (width, height) => {
        return d3
            .select(canvas.current)
            .append('svg')
            .style('background', 'var(--item-background)')
            .style('width', width)
            .style('height', height)
    }

    const createSankey = (width, height) => {
        return new Sankey.sankey()
            .nodeId((d) => d.name)
            .nodeAlign(Sankey.sankeyJustify)
            .nodeSort(null)
            .nodeWidth(15)
            .size([width, height])
    }

    const appendPathNodes = (svg, nodes) => {
        svg.append('g')
            .selectAll('rect')
            .data(nodes)
            .join('rect')
            .attr('x', (d) => d.x0 + 1)
            .attr('y', (d) => d.y0)
            .attr('height', (d) => d.y1 - d.y0)
            .attr('width', (d) => d.x1 - d.x0 - 2)
            .attr('fill', (d) => {
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
                if (isSelectedPathStartOrEnd(d)) {
                    return d3.color('purple')
                }
                const startNodeColor = d3.color(c)
                    ? d3.color(c)
                    : color === 'white' // is this ever not white?
                    ? d3.color('#5375ff')
                    : d3.color('#191919')
                return startNodeColor
            })
            .on('mouseover', (data) => {
                if (data.y1 - data.y0 > HIDE_PATH_CARD_HEIGHT) {
                    return
                }
                setPathItemCards(
                    nodes.map((node) =>
                        node.index === data.index
                            ? { ...node, visible: true }
                            : { ...node, visible: node.y1 - node.y0 > HIDE_PATH_CARD_HEIGHT }
                    )
                )
            })
            .append('title')
            .text((d) => `${stripHTTP(d.name)}\n${d.value.toLocaleString()}`)
    }

    const appendDropoffs = (svg) => {
        const dropOffGradient = svg
            .append('defs')
            .append('linearGradient')
            .attr('id', 'dropoff-gradient')
            .attr('gradientTransform', 'rotate(90)')

        dropOffGradient
            .append('stop')
            .attr('offset', '0%')
            .attr('stop-color', color === 'white' ? 'rgba(220,53,69,0.7)' : 'rgb(220,53,69)')

        dropOffGradient
            .append('stop')
            .attr('offset', '100%')
            .attr('stop-color', color === 'white' ? '#fff' : 'var(--item-background)')
    }

    const appendPathLinks = (svg, links) => {
        const link = svg
            .append('g')
            .attr('fill', 'none')
            .selectAll('g')
            .data(links)
            .join('g')
            .attr('stroke', () => (color === 'white' ? 'var(--primary)' : 'var(--item-lighter'))
            .attr('opacity', 0.2)

        link.append('path')
            .attr('d', Sankey.sankeyLinkHorizontal())
            .attr('id', (d) => `path-${d.index}`)
            .attr('stroke-width', (d) => {
                return Math.max(1, d.width)
            })
            .on('mouseover', (data) => {
                svg.select(`#path-${data.index}`).attr('stroke', 'blue')
                if (data?.source?.targetLinks.length === 0) {
                    return
                }
                let nodesToColor = [data.source]
                while (nodesToColor.length > 0) {
                    let _node = nodesToColor.pop()
                    _node.targetLinks.forEach((_link) => {
                        svg.select(`#path-${_link.index}`).attr('stroke', 'blue')
                        nodesToColor.push(_link.source)
                    })
                }
            })
            .on('mouseleave', () => {
                svg.selectAll('path').attr('stroke', 'var(--primary)')
            })

        link.append('g')
            .append('path')
            .attr('d', (data) => {
                if (data.source.layer === 0) {
                    return
                }
                let _height =
                    data.source.y1 -
                    data.source.y0 -
                    data.source.sourceLinks.reduce((prev, curr) => prev + curr.width, 0)
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

    function renderPaths() {
        const elements = document
            .getElementById(`'${dashboardItemId || DEFAULT_PATHS_ID}'`)
            .querySelectorAll(`.paths svg`)
        elements.forEach((node) => node.parentNode.removeChild(node))

        if (!paths || paths.nodes.length === 0) {
            setPathItemCards([])
            return
        }

        const width = canvas.current.offsetWidth
        const height = canvas.current.offsetHeight

        const svg = createCanvas(width, height)

        const sankey = createSankey(width, height)

        const { nodes, links } = sankey(paths)
        setPathItemCards(nodes.map((node) => ({ ...node, visible: node.y1 - node.y0 > HIDE_PATH_CARD_HEIGHT })))

        appendPathNodes(svg, nodes)
        appendDropoffs(svg)
        appendPathLinks(svg, links)
    }

    const getDropOffValue = (pathItemCard) => {
        return pathItemCard.value - pathItemCard.sourceLinks.reduce((prev, curr) => prev + curr.value, 0)
    }

    const getContinuingValue = (sourceLinks) => {
        return sourceLinks.reduce((prev, curr) => prev + curr.value, 0)
    }

    const isSelectedPathStartOrEnd = (pathItemCard) => {
        const cardName = pageUrl(pathItemCard)
        const isPathStart = pathItemCard.targetLinks.length === 0
        const isPathEnd = pathItemCard.sourceLinks.length === 0
        return (
            (filter.start_point === cardName && isPathStart) ||
            (filter.end_point === cardName && isPathEnd) ||
            (filter.funnel_paths === FunnelPathType.between &&
                ((cardName === filter.funnel_filter.events[filter.funnel_filter.funnel_step - 1].name && isPathEnd) ||
                    (cardName === filter.funnel_filter.events[filter.funnel_filter.funnel_step - 2].name &&
                        isPathStart)))
        )
    }

    return (
        <div
            style={{
                position: 'relative',
            }}
            id={`'${dashboardItemId || DEFAULT_PATHS_ID}'`}
        >
            <div ref={canvas} className="paths" data-attr="paths-viz">
                {!pathsLoading && paths && paths.nodes.length === 0 && !paths.error && <NoData />}
                {!paths.error &&
                    pathItemCards &&
                    pathItemCards.map((pathItemCard, idx) => {
                        const continuingValue = getContinuingValue(pathItemCard.sourceLinks)
                        const dropOffValue = getDropOffValue(pathItemCard)
                        return (
                            <>
                                <Tooltip title={pageUrl(pathItemCard)} placement="right">
                                    <Dropdown
                                        key={idx}
                                        overlay={
                                            <Menu
                                                style={{
                                                    marginTop: -5,
                                                    border: '1px solid var(--border)',
                                                    borderRadius: '0px 0px 4px 4px',
                                                    width: 200,
                                                }}
                                            >
                                                {pathItemCard.sourceLinks.length > 0 && (
                                                    <Menu.Item
                                                        disabled
                                                        className="pathcard-dropdown-info-option text-small"
                                                        style={{
                                                            borderBottom: `${
                                                                dropOffValue > 0 || pathItemCard.targetLinks.length > 0
                                                                    ? '1px solid var(--border)'
                                                                    : ''
                                                            }`,
                                                        }}
                                                    >
                                                        <span className="text-small">
                                                            <span style={{ paddingRight: 8 }}>
                                                                <PathsCompletedArrow />
                                                            </span>{' '}
                                                            Continuing
                                                        </span>{' '}
                                                        <span className="primary text-small">
                                                            <ValueInspectorButton
                                                                style={{ paddingRight: 0, fontSize: 12 }}
                                                                onClick={() => openPersonsModal(pathItemCard.name)}
                                                            >
                                                                {continuingValue}
                                                                <span
                                                                    className="text-muted-alt"
                                                                    style={{ paddingLeft: 4 }}
                                                                >
                                                                    (
                                                                    {(
                                                                        (continuingValue / pathItemCard.value) *
                                                                        100
                                                                    ).toFixed(1)}
                                                                    %)
                                                                </span>
                                                            </ValueInspectorButton>
                                                        </span>
                                                    </Menu.Item>
                                                )}
                                                {dropOffValue > 0 && (
                                                    <Menu.Item
                                                        disabled
                                                        className="pathcard-dropdown-info-option text-small"
                                                        style={{
                                                            borderBottom: '1px solid var(--border)',
                                                        }}
                                                    >
                                                        <span className="text-small" style={{ display: 'flex' }}>
                                                            <span
                                                                style={{
                                                                    paddingRight: 8,
                                                                    display: 'flex',
                                                                    alignItems: 'center',
                                                                }}
                                                            >
                                                                <PathsDropoffArrow />
                                                            </span>{' '}
                                                            Dropping off
                                                        </span>{' '}
                                                        <span className="primary">
                                                            <ValueInspectorButton
                                                                style={{ paddingRight: 0, fontSize: 12 }}
                                                                onClick={() =>
                                                                    openPersonsModal(
                                                                        undefined,
                                                                        undefined,
                                                                        pathItemCard.name
                                                                    )
                                                                }
                                                            >
                                                                {dropOffValue}{' '}
                                                                <span
                                                                    className="text-muted-alt text-small"
                                                                    style={{ paddingLeft: 4 }}
                                                                >
                                                                    (
                                                                    {(
                                                                        (dropOffValue / pathItemCard.value) *
                                                                        100
                                                                    ).toFixed(1)}
                                                                    %)
                                                                </span>
                                                            </ValueInspectorButton>
                                                        </span>
                                                    </Menu.Item>
                                                )}
                                                {pathItemCard.targetLinks.length > 0 && (
                                                    <Menu.Item
                                                        disabled
                                                        className="pathcard-dropdown-info-option"
                                                        style={{
                                                            padding: '5px 8px',
                                                            fontWeight: 500,
                                                            fontSize: 12,
                                                        }}
                                                    >
                                                        <ClockCircleOutlined
                                                            style={{ color: 'var(--muted)', fontSize: 16 }}
                                                        />
                                                        <span
                                                            className="text-small"
                                                            style={{
                                                                wordWrap: 'break-word',
                                                                whiteSpace: 'normal',
                                                                paddingLeft: 8,
                                                            }}
                                                        >
                                                            Average time from previous step{' '}
                                                        </span>
                                                        {humanFriendlyDuration(
                                                            pathItemCard.targetLinks[0].average_conversion_time / 1000
                                                        )}
                                                    </Menu.Item>
                                                )}
                                            </Menu>
                                        }
                                        placement="bottomCenter"
                                    >
                                        <Button
                                            key={idx}
                                            style={{
                                                position: 'absolute',
                                                left:
                                                    pathItemCard.sourceLinks.length === 0
                                                        ? pathItemCard.x0 - (200 - 7)
                                                        : pathItemCard.x0 + 7,
                                                top:
                                                    pathItemCard.sourceLinks.length > 0
                                                        ? pathItemCard.y0 + 5
                                                        : pathItemCard.y0 + (pathItemCard.y1 - pathItemCard.y0) / 2,
                                                background: 'white',
                                                width: 200,
                                                border: `1px solid ${
                                                    isSelectedPathStartOrEnd(pathItemCard) ? 'purple' : 'var(--border)'
                                                }`,
                                                padding: 4,
                                                justifyContent: 'space-between',
                                                alignItems: 'center',
                                                display: `${pathItemCard.visible ? 'flex' : 'none'}`,
                                            }}
                                        >
                                            <div style={{ display: 'flex', alignItems: 'center' }}>
                                                <span
                                                    className="text-muted"
                                                    style={{
                                                        fontSize: 10,
                                                        fontWeight: 600,
                                                        marginRight: 4,
                                                        lineHeight: '10px',
                                                    }}
                                                >{`0${pathItemCard.name[0]}`}</span>{' '}
                                                <span style={{ fontSize: 12, fontWeight: 600 }}>
                                                    {pageUrl(pathItemCard, true)}
                                                </span>
                                            </div>
                                            <Row style={{ alignSelf: 'center' }}>
                                                <span
                                                    onClick={() => openPersonsModal(undefined, pathItemCard.name)}
                                                    className="primary text-small"
                                                    style={{ alignSelf: 'center', paddingRight: 4, fontWeight: 500 }}
                                                >
                                                    {continuingValue + dropOffValue}
                                                </span>
                                                <Dropdown
                                                    trigger={['click']}
                                                    overlay={
                                                        <Menu className="paths-options-dropdown">
                                                            <Menu.Item
                                                                onClick={() =>
                                                                    setFilter({ start_point: pageUrl(pathItemCard) })
                                                                }
                                                            >
                                                                Set as path start
                                                            </Menu.Item>
                                                            <Menu.Item
                                                                onClick={() =>
                                                                    setFilter({ end_point: pageUrl(pathItemCard) })
                                                                }
                                                            >
                                                                Set as path end
                                                            </Menu.Item>
                                                            <Menu.Item
                                                                onClick={() => {
                                                                    if (
                                                                        filter &&
                                                                        filter.exclude_events &&
                                                                        filter.exclude_events.length > 0
                                                                    ) {
                                                                        const exclusionEvents =
                                                                            filter.exclude_events.map((event) => ({
                                                                                value: event,
                                                                            }))
                                                                        updateExclusions([
                                                                            ...exclusionEvents,
                                                                            { value: pageUrl(pathItemCard) },
                                                                        ])
                                                                    } else {
                                                                        updateExclusions([
                                                                            { value: pageUrl(pathItemCard) },
                                                                        ])
                                                                    }
                                                                }}
                                                            >
                                                                Exclude path item
                                                            </Menu.Item>
                                                            <Menu.Item onClick={() => viewPathToFunnel(pathItemCard)}>
                                                                View funnel
                                                            </Menu.Item>
                                                            <Menu.Item
                                                                onClick={() => copyToClipboard(pageUrl(pathItemCard))}
                                                            >
                                                                Copy path item name
                                                            </Menu.Item>
                                                        </Menu>
                                                    }
                                                >
                                                    <div className="paths-dropdown-ellipsis">...</div>
                                                </Dropdown>
                                            </Row>
                                        </Button>
                                    </Dropdown>
                                </Tooltip>
                            </>
                        )
                    })}
            </div>
        </div>
    )
}
