import React, { useRef, useState, useEffect } from 'react'
import api from 'lib/api'
import { useValues } from 'kea'
import { stripHTTP } from 'lib/utils'
import { Modal, Button, Spin } from 'antd'
import { EventElements } from 'scenes/events/EventElements'
import * as d3 from 'd3'
import * as Sankey from 'd3-sankey'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { useWindowSize } from 'lib/hooks/useWindowSize'

// TODO: Replace with PathType enums when moving to TypeScript
const PAGEVIEW = '$pageview'
const AUTOCAPTURE = '$autocapture'

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

function pageUrl(d) {
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

    try {
        const url = new URL(name)
        name = incomingDomains.length !== 1 ? url.href.replace(/(^\w+:|^)\/\//, '') : url.pathname + url.search
    } catch {
        // discard if invalid url
    }

    return name.length > 35 ? name.substring(0, 6) + '...' + name.slice(-15) : name
}

function pathText(d) {
    const name = d.name.replace(/(^[0-9]+_)/, '')
    return name.length > 35 ? name.substring(0, 6) + '...' + name.slice(-15) : name
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

export function Paths({ dashboardItemId = null, filters = null, color = 'white' }) {
    const canvas = useRef(null)
    const size = useWindowSize()
    const { paths, loadedFilter, resultsLoading: pathsLoading } = useValues(pathsLogic({ dashboardItemId, filters }))

    const [modalVisible, setModalVisible] = useState(false)
    const [event, setEvent] = useState(null)

    useEffect(() => {
        renderPaths()
    }, [paths, !pathsLoading, size, color])

    function renderPaths() {
        const elements = document
            .getElementById(`'${dashboardItemId || DEFAULT_PATHS_ID}'`)
            .querySelectorAll(`.paths svg`)
        elements.forEach((node) => node.parentNode.removeChild(node))

        if (!paths || paths.nodes.length === 0) {
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
            .nodeAlign(Sankey.sankeyLeft)
            .nodeSort(null)
            .nodeWidth(15)
            .size([width, height])

        const { nodes, links } = sankey({
            nodes: paths.nodes.map((d) => ({ ...d })),
            links: paths.links.map((d) => ({ ...d })),
        })

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
                    ? d3.color('#dddddd')
                    : d3.color('#191919')
                return startNodeColor.darker(0.5)
            })
            .attr('opacity', 0.5)
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
            .attr('opacity', 0.4)

        link.append('path')
            .attr('d', Sankey.sankeyLinkHorizontal())
            .attr('stroke-width', (d) => {
                return Math.max(1, d.width)
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
            .append('tspan')
            .text((d) => {
                return d.value - d.source.sourceLinks.reduce((prev, curr) => prev + curr.value, 0)
            })

        link.append('title').text(
            (d) => `${stripHTTP(d.source.name)} → ${stripHTTP(d.target.name)}\n${d.value.toLocaleString()}`
        )

        var textSelection = svg
            .append('g')
            .style('font-size', '12px')
            .selectAll('text')
            .data(nodes)
            .join('text')
            .attr('x', (d) => (d.x0 < width / 2 ? d.x1 + 6 : d.x0 - 6))
            .attr('y', (d) => (d.y1 + d.y0) / 2)
            .attr('dy', '0.35em')
            .attr('text-anchor', (d) => (d.x0 < width / 2 ? 'start' : 'end'))
            .attr('display', (d) => (d.value > 0 ? 'inherit' : 'none'))
            .text(loadedFilter?.path_type === PAGEVIEW ? pageUrl : pathText)
            .on('click', async (node) => {
                if (loadedFilter.path_type === AUTOCAPTURE) {
                    setModalVisible(true)
                    setEvent(null)
                    let result = await api.get('api/event/' + node.id)
                    setEvent(result)
                }
            })
            .style('cursor', loadedFilter.path_type === AUTOCAPTURE ? 'pointer' : 'auto')
            .style('fill', color === 'white' ? '#000' : '#fff')

        textSelection
            .append('tspan')
            .attr('fill-opacity', 0.8)
            .text((d) => ` ${d.value.toLocaleString()}`)

        textSelection.append('title').text((d) => stripHTTP(d.name))

        return textSelection.node()
    }

    return (
        <div>
            {loadedFilter.path_type === AUTOCAPTURE && (
                <div style={{ margin: 10 }}>Click on a tag to see related DOM tree</div>
            )}
            <div
                style={{
                    position: 'relative',
                }}
                id={`'${dashboardItemId || DEFAULT_PATHS_ID}'`}
            >
                <div ref={canvas} className="paths" data-attr="paths-viz">
                    {!pathsLoading && paths && paths.nodes.length === 0 && !paths.error && <NoData />}
                </div>
            </div>
            <Modal
                visible={modalVisible}
                onOk={() => setModalVisible(false)}
                onCancel={() => setModalVisible(false)}
                closable={false}
                style={{ minWidth: '50%' }}
                footer={[
                    <Button key="submit" type="primary" onClick={() => setModalVisible(false)}>
                        Ok
                    </Button>,
                ]}
                bodyStyle={
                    !event
                        ? {
                              alignItems: 'center',
                              justifyContent: 'center',
                          }
                        : {}
                }
            >
                {event ? <EventElements event={event} /> : <Spin />}
            </Modal>
        </div>
    )
}
