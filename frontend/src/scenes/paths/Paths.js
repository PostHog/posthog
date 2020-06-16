import React, { useRef, useState, useEffect } from 'react'
import api from 'lib/api'
import { Card, Loading, stripHTTP } from 'lib/utils'
import { DateFilter } from 'lib/components/DateFilter'
import { Row, Modal, Button, Spin, Select } from 'antd'
import { EventElements } from 'scenes/events/EventElements'
import * as d3 from 'd3'
import * as Sankey from 'd3-sankey'
import { PropertyFilters, PropertyValue } from 'lib/components/PropertyFilters'
import { useActions, useValues } from 'kea'
import { hot } from 'react-hot-loader/root'
import {
    pathsLogic,
    PAGEVIEW,
    AUTOCAPTURE,
    CUSTOM_EVENT,
    pathOptionsToLabels,
    pathOptionsToProperty,
} from 'scenes/paths/pathsLogic'
import { userLogic } from 'scenes/userLogic'

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

function NoData() {
    return (
        <div style={{ padding: '1rem' }}>
            We don't have enough data to show anything here. You might need to send us some frontend (JS) events, as we
            use the <pre style={{ display: 'inline' }}>$current_url</pre> property to calculate paths.
        </div>
    )
}

export const Paths = hot(_Paths)
function _Paths() {
    const canvas = useRef(null)
    const { paths, filter, pathsLoading } = useValues(pathsLogic)
    const { setFilter } = useActions(pathsLogic)
    const { customEventNames } = useValues(userLogic)

    const [modalVisible, setModalVisible] = useState(false)
    const [eventelements, setEventelements] = useState(null)

    useEffect(() => {
        renderPaths()
    }, [paths, !pathsLoading])

    function renderPaths() {
        const elements = document.querySelectorAll('.paths svg')
        elements.forEach(node => node.parentNode.removeChild(node))

        if (!paths || paths.nodes.length === 0) {
            return
        }
        let width = canvas.current.offsetWidth
        let height = canvas.current.offsetHeight

        let svg = d3
            .select(canvas.current)
            .append('svg')
            .style('background', '#fff')
            .style('width', width)
            .style('height', height)
        let sankey = new Sankey.sankey()
            .nodeId(d => d.name)
            .nodeAlign(Sankey.sankeyLeft)
            .nodeSort(null)
            .nodeWidth(15)
            .size([width, height])

        const { nodes, links } = sankey({
            nodes: paths.nodes.map(d => Object.assign({}, d)),
            links: paths.links.map(d => Object.assign({}, d)),
        })

        svg.append('g')
            .selectAll('rect')
            .data(nodes)
            .join('rect')
            .attr('x', d => d.x0 + 1)
            .attr('y', d => d.y0)
            .attr('height', d => d.y1 - d.y0)
            .attr('width', d => d.x1 - d.x0 - 2)
            .attr('fill', d => {
                let c
                for (const link of d.sourceLinks) {
                    if (c === undefined) c = link.color
                    else if (c !== link.color) c = null
                }
                if (c === undefined)
                    for (const link of d.targetLinks) {
                        if (c === undefined) c = link.color
                        else if (c !== link.color) c = null
                    }
                return (d3.color(c) || d3.color('#dddddd')).darker(0.5)
            })
            .attr('opacity', 0.5)
            .append('title')
            .text(d => `${stripHTTP(d.name)}\n${d.value.toLocaleString()}`)

        const dropOffGradient = svg
            .append('defs')
            .append('linearGradient')
            .attr('id', 'dropoff-gradient')
            .attr('gradientTransform', 'rotate(90)')

        dropOffGradient
            .append('stop')
            .attr('offset', '0%')
            .attr('stop-color', 'rgba(220,53,69,0.7)')

        dropOffGradient
            .append('stop')
            .attr('offset', '100%')
            .attr('stop-color', '#ffffff')

        const link = svg
            .append('g')
            .attr('fill', 'none')
            .selectAll('g')
            .data(links)
            .join('g')
            .attr('stroke', () => 'var(--blue)')
            .attr('opacity', 0.3)
            .style('mix-blend-mode', 'multiply')

        link.append('path')
            .attr('d', Sankey.sankeyLinkHorizontal())
            .attr('stroke-width', d => {
                return Math.max(1, d.width)
            })

        link.append('g')
            .append('path')
            .attr('d', data => {
                if (data.source.layer == 0) return
                let height =
                    data.source.y1 -
                    data.source.y0 -
                    data.source.sourceLinks.reduce((prev, curr) => prev + curr.width, 0)
                return rounded_rect(0, 0, 30, height, Math.min(25, height), false, true, false, false)
            })
            .attr('fill', 'url(#dropoff-gradient)')
            .attr('stroke-width', 0)
            .attr('transform', data => {
                return (
                    'translate(' +
                    Math.round(data.source.x1) +
                    ',' +
                    Math.round(data.source.y0 + data.source.sourceLinks.reduce((prev, curr) => prev + curr.width, 0)) +
                    ')'
                )
            })
            .append('tspan')
            .text(d => {
                return d.value - d.source.sourceLinks.reduce((prev, curr) => prev + curr.value, 0)
            })

        link.append('title').text(
            d => `${stripHTTP(d.source.name)} → ${stripHTTP(d.target.name)}\n${d.value.toLocaleString()}`
        )

        var textSelection = svg
            .append('g')
            .style('font-size', '12px')
            .selectAll('text')
            .data(nodes)
            .join('text')
            .attr('x', d => (d.x0 < width / 2 ? d.x1 + 6 : d.x0 - 6))
            .attr('y', d => (d.y1 + d.y0) / 2)
            .attr('dy', '0.35em')
            .attr('text-anchor', d => (d.x0 < width / 2 ? 'start' : 'end'))
            .attr('display', d => (d.value > 0 ? 'inherit' : 'none'))
            .text(d =>
                d.name.length > 35
                    ? stripHTTP(d.name).substring(0, 6) + '...' + stripHTTP(d.name).slice(-15)
                    : stripHTTP(d.name)
            )
            .on('click', async node => {
                if (filter.type == AUTOCAPTURE) {
                    setModalVisible(true)
                    setEventelements(null)
                    let result = await api.get('api/event/' + node.id)
                    setEventelements(result)
                }
            })
            .style('cursor', filter.type == AUTOCAPTURE ? 'pointer' : 'auto')

        textSelection
            .append('tspan')
            .attr('fill-opacity', 0.7)
            .text(d => ` ${d.value.toLocaleString()}`)

        textSelection.append('title').text(d => stripHTTP(d.name))

        return textSelection.node()
    }

    return (
        <div>
            <h1 className="page-header">Paths</h1>
            <PropertyFilters pageKey="Paths" />
            <Card
                title={
                    <Row justify="space-between">
                        <Row>
                            <Row align="middle">
                                Path Type:
                                <Select
                                    value={filter.type || PAGEVIEW}
                                    bordered={false}
                                    defaultValue={PAGEVIEW}
                                    dropdownMatchSelectWidth={false}
                                    onChange={value => setFilter({ type: value, start: null })}
                                    style={{ paddingTop: 2 }}
                                >
                                    {Object.entries(pathOptionsToLabels).map(([value, name], index) => {
                                        return (
                                            <Select.Option key={index} value={value}>
                                                {name}
                                            </Select.Option>
                                        )
                                    })}
                                </Select>
                            </Row>

                            <Row align="middle">
                                Start:
                                <PropertyValue
                                    endpoint={filter.type === AUTOCAPTURE && 'api/paths/elements'}
                                    outerOptions={
                                        filter.type === CUSTOM_EVENT &&
                                        customEventNames.map(name => ({
                                            name,
                                        }))
                                    }
                                    onSet={value => setFilter({ start: value })}
                                    propertyKey={pathOptionsToProperty[filter.type]}
                                    type="event"
                                    style={{ width: 200, paddingTop: 2 }}
                                    bordered={false}
                                    value={filter.start}
                                    placeholder={'Select start element'}
                                ></PropertyValue>
                            </Row>
                        </Row>
                        <Row align="middle">
                            <DateFilter
                                onChange={(date_from, date_to) =>
                                    setFilter({
                                        date_from,
                                        date_to,
                                    })
                                }
                                dateFrom={filter.date_from}
                                dateTo={filter.date_to}
                            />
                        </Row>
                    </Row>
                }
            >
                {filter.type == AUTOCAPTURE && <div style={{ margin: 10 }}>Click on a tag to see related DOM tree</div>}
                <div ref={canvas} className="paths" style={{ height: '90vh' }} data-attr="paths-viz">
                    {!pathsLoading && paths && paths.nodes.length === 0 ? (
                        <NoData />
                    ) : (
                        pathsLoading && (
                            <div className="loading-overlay mt-5">
                                <div />
                                <Loading />
                                <br />
                            </div>
                        )
                    )}
                </div>
            </Card>
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
                    !eventelements
                        ? {
                              alignItems: 'center',
                              justifyContent: 'center',
                          }
                        : {}
                }
            >
                {eventelements ? <EventElements event={eventelements}></EventElements> : <Spin />}
            </Modal>
        </div>
    )
}
