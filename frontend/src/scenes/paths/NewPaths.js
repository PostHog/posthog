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

function rounded_rect(x, y, w, h, r, tl, tr, bl, br) {
    var retval
    retval = 'M' + (x + r) + ',' + y
    retval += 'h' + (w - 2 * r)
    if (tr) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + r
    } else {
        retval += 'h' + r
        retval += 'v' + r
    }
    retval += 'v' + (h - 2 * r)
    if (br) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + -r + ',' + r
    } else {
        retval += 'v' + r
        retval += 'h' + -r
    }
    retval += 'h' + (2 * r - w)
    if (bl) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + -r + ',' + -r
    } else {
        retval += 'h' + -r
        retval += 'v' + -r
    }
    retval += 'v' + (2 * r - h)
    if (tl) {
        retval += 'a' + r + ',' + r + ' 0 0 1 ' + r + ',' + -r
    } else {
        retval += 'v' + -r
        retval += 'h' + r
    }
    retval += 'z'
    return retval
}

function pageUrl(d, display) {
    const incomingUrls = d.targetLinks
        .map((l) => l?.source?.name?.replace(/(^[0-9]+_)/, ''))
        .filter((a) => {
            try {
                new URL(a)
            } catch {
                return false
            }
            return a
        })
        .map((a) => new URL(a))
    const incomingDomains = [...new Set(incomingUrls.map((url) => url.origin))]

    let name = d.name.replace(/(^[0-9]+_)/, '')

    if (!display) {
        return name
    }

    try {
        const url = new URL(name)
        name = incomingDomains.length !== 1 ? url.href.replace(/(^\w+:|^)\/\//, '') : url.pathname + url.search
    } catch {
        // discard if invalid url
    }
    return name.length > 15 ? name.substring(0, 6) + '...' + name.slice(-8) : name
}

function NoData() {
    return (
        <div style={{ padding: '1rem' }}>
            We don't have enough data to show anything here. You might need to send us some frontend (JS) events, as we
            use the <pre style={{ display: 'inline' }}>$current_url</pre> property to calculate paths.
        </div>
    )
}

const DEFAULT_PATHS_ID = 'default_paths'

export function NewPaths({ dashboardItemId = null, filters = null, color = 'white' }) {
    const canvas = useRef(null)
    const size = useWindowSize()
    const hidePathCardHeight = 30
    const { paths, resultsLoading: pathsLoading, filter } = useValues(pathsLogic({ dashboardItemId, filters }))
    const { openPersonsModal, setFilter, updateExclusions, viewPathToFunnel } = useActions(
        pathsLogic({ dashboardItemId, filters })
    )
    const [pathItemCards, setPathItemCards] = useState([])
    useEffect(() => {
        setPathItemCards([])
        renderPaths()
    }, [paths, !pathsLoading, size, color])

    function renderPaths() {
        const elements = document
            .getElementById(`'${dashboardItemId || DEFAULT_PATHS_ID}'`)
            .querySelectorAll(`.paths svg`)
        elements.forEach((node) => node.parentNode.removeChild(node))

        if (!paths || paths.nodes.length === 0) {
            setPathItemCards([])
            return
        }
        let width = canvas.current.offsetWidth
        let height = canvas.current.offsetHeight

        let svg = d3
            .select(canvas.current)
            .append('svg')
            .style('background', 'var(--item-background)')
            .style('width', width)
            .style('height', height)

        let sankey = new Sankey.sankey()
            .nodeId((d) => d.name)
            .nodeAlign(Sankey.sankeyJustify)
            .nodeSort(null)
            .nodeWidth(15)
            .size([width, height])

        const { nodes, links } = sankey(paths)
        setPathItemCards(nodes.map((node) => ({ ...node, visible: node.y1 - node.y0 > hidePathCardHeight })))

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

                const startNodeColor = d3.color(c)
                    ? d3.color(c)
                    : color === 'white'
                    ? d3.color('#5375ff')
                    : d3.color('#191919')
                return startNodeColor
            })
            .on('mouseover', (data) => {
                if (data.y1 - data.y0 > hidePathCardHeight) {
                    return
                }
                setPathItemCards(
                    nodes.map((node) =>
                        node.index === data.index
                            ? { ...node, visible: true }
                            : { ...node, visible: node.y1 - node.y0 > hidePathCardHeight }
                    )
                )
            })
            .append('title')
            .text((d) => `${stripHTTP(d.name)}\n${d.value.toLocaleString()}`)

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
            .attr('id', (d) => `path${d.index}`)
            .attr('stroke-width', (d) => {
                return Math.max(1, d.width)
            })
            .on('mouseover', (data) => {
                svg.select(`#path${data.index}`).attr('stroke', 'blue')
                if (data?.source?.targetLinks.length === 0) {
                    return
                }
                let node = data.source
                while (node.targetLinks.length > 0) {
                    svg.select(`#path${node.targetLinks[0].index}`).attr('stroke', 'blue')
                    node = node.targetLinks[0].source
                }
            })
            .on('mouseleave', () => svg.selectAll('path').attr('stroke', 'var(--primary)'))

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
                return rounded_rect(0, 0, 30, _height, Math.min(25, _height), false, true, false, false)
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

    const getDropOffValue = (pathItemCard) => {
        return pathItemCard.value - pathItemCard.sourceLinks.reduce((prev, curr) => prev + curr.value, 0)
    }

    const getContinuingValue = (sourceLinks) => {
        return sourceLinks.reduce((prev, curr) => prev + curr.value, 0)
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
                                <Tooltip title={pageUrl(pathItemCard)}>
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
                                                border: '1px solid var(--border)',
                                                padding: 4,
                                                justifyContent: 'space-between',
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
