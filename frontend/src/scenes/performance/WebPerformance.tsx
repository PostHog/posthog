import React, { useState } from 'react'
import { Button, Col, Collapse, Popover, Row, Typography } from 'antd'
import './WebPerformance.scss'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PageHeader } from 'lib/components/PageHeader'
import clsx from 'clsx'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { EventType } from '~/types'
import { TZLabel } from 'lib/components/TimezoneAware'
import { EyeOutlined } from '@ant-design/icons'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/components/Tooltip'
import { useActions, useValues } from 'kea'
import {
    MinimalPerformanceResourceTiming,
    ResourceTiming,
    webPerformanceLogic,
} from 'scenes/performance/webPerformanceLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { getChartColors } from 'lib/colors'
import { areObjectValuesEmpty, humanizeBytes } from 'lib/utils'
import { Popup } from 'lib/components/Popup/Popup'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

interface PerfBlockProps {
    resourceTiming: ResourceTiming
    max: number | undefined
}

const toPositionStyle = (
    start: number,
    end: number,
    max: number
): { right: number; blockSides: { left: string; right: string } } | null => {
    if (!start && !end) {
        return null
    }
    const left = (start / max) * 100
    const right = 100 - (end / max) * 100
    const blockSides = { left: `${left}%`, right: `${right}%` }

    return { right, blockSides }
}
const colors = getChartColors('green')

const overlayFor = (resourceTiming: ResourceTiming): JSX.Element => {
    const title = typeof resourceTiming.item == 'string' ? resourceTiming.item : resourceTiming.item.pathname
    const url = typeof resourceTiming.item == 'string' ? null : resourceTiming.item.host
    const asResourceTiming = resourceTiming.entry as PerformanceResourceTiming
    return (
        <>
            {url && <Typography.Text type="secondary">{url}</Typography.Text>}
            <h2>{title}</h2>
            <hr />
            <p>
                started at {resourceTiming.entry.startTime || resourceTiming.entry.fetchStart}ms and took{' '}
                {resourceTiming.entry.duration}ms to complete
            </p>
            {Object.entries(resourceTiming.performanceParts).map(([key, part], index) => (
                <p key={index}>
                    {key}: from: {part.start}ms to {part.end}ms (
                    {(((part.end - part.start) / resourceTiming.entry.duration) * 100).toFixed(1)}%)
                </p>
            ))}
            {asResourceTiming.decodedBodySize && asResourceTiming.encodedBodySize && (
                <>
                    <hr />
                    Resource is {humanizeBytes(asResourceTiming.decodedBodySize)}
                    {asResourceTiming.encodedBodySize !== asResourceTiming.decodedBodySize && (
                        <p>
                            Was compressed. Sent {humanizeBytes(asResourceTiming.encodedBodySize)}. Saving{' '}
                            {(
                                ((asResourceTiming.decodedBodySize - asResourceTiming.encodedBodySize) /
                                    asResourceTiming.decodedBodySize) *
                                100
                            ).toFixed(1)}
                            %
                        </p>
                    )}
                </>
            )}
            <hr />
        </>
    )
}

export const PerfBlock = ({ resourceTiming, max }: PerfBlockProps): JSX.Element => {
    if (max) {
        let right = 0
        let end = 0
        let blocks: JSX.Element[]

        if (areObjectValuesEmpty(resourceTiming.performanceParts)) {
            const minimalEntry = resourceTiming.entry as MinimalPerformanceResourceTiming
            const style = toPositionStyle(minimalEntry.fetchStart, minimalEntry.responseEnd, max)
            right = style?.right ?? 100
            end = minimalEntry.responseEnd

            blocks = [
                <div
                    key={minimalEntry.name}
                    className="performance-block positioned"
                    data-attr-name={minimalEntry.name}
                    style={{ ...style?.blockSides, backgroundColor: resourceTiming.color }}
                />,
            ]
        } else {
            blocks = Object.entries(resourceTiming.performanceParts).map(([name, measure], index) => {
                const style = toPositionStyle(measure.start, measure.end, max)
                right = style?.right ?? 100
                end = measure.end
                return (
                    <div
                        key={name}
                        className={clsx('performance-block positioned', measure.reducedHeight && 'reduced-height')}
                        data-attr-name={name}
                        style={{ ...style?.blockSides, backgroundColor: colors[index] }}
                    />
                )
            })
        }

        const [mouseIsOver, setMouseIsOver] = useState(false)

        const textPosition = { left: `${100 - right + 1}%`, right: `${right}%` }
        return (
            <Popup overlay={overlayFor(resourceTiming)} visible={mouseIsOver}>
                <div onMouseEnter={() => setMouseIsOver(true)} onMouseLeave={() => setMouseIsOver(false)}>
                    {blocks}
                    <div className="positioned" style={textPosition}>
                        {Math.round(end)}ms
                    </div>
                </div>
            </Popup>
        )
    } else {
        return <></>
    }
}

const pointInTimeContent = {
    domComplete: (
        <div>
            The document and all sub-resources have finished loading. The state indicates that the load event is about
            to fire.{' '}
            <a href="https://developer.mozilla.org/en-US/docs/Web/API/Document/readyState" target="_blank">
                Read more on the mozilla developer network
            </a>
        </div>
    ),
    domInteractive: (
        <div>
            The document has finished loading and the document has been parsed but sub-resources such as scripts,
            images, stylesheets and frames are still loading.{' '}
            <a href="https://developer.mozilla.org/en-US/docs/Web/API/Document/readyState" target="_blank">
                Read more on the mozilla developer network
            </a>
        </div>
    ),
    pageLoaded: (
        <div>
            The load event is fired when the whole page has loaded, including all dependent resources such as
            stylesheets and images. This is in contrast to DOMContentLoaded, which is fired as soon as the page DOM has
            been loaded, without waiting for resources to finish loading.{' '}
            <a href="https://developer.mozilla.org/en-US/docs/Web/API/Window/load_event" target="_blank">
                Read more on the mozilla developer network
            </a>
        </div>
    ),
}

const pointInTimeContentFor = (pointInTimeMarker: string): JSX.Element =>
    pointInTimeContent[pointInTimeMarker] ?? <div>Unknown marker: {pointInTimeMarker}</div>

const VerticalMarker = ({
    max,
    position,
    color,
    bringToFront,
}: {
    max: number | undefined
    position: number
    color: string
    bringToFront?: boolean
}): JSX.Element => {
    if (max) {
        const left = (position / max) * 100
        return (
            <div
                className={clsx(['vertical-marker', { 'in-front': bringToFront }])}
                style={{ left: `${left}%`, backgroundColor: color }}
            />
        )
    } else {
        return <></>
    }
}

const WaterfallChart = (): JSX.Element => {
    const { eventToDisplay } = useValues(webPerformanceLogic)
    return (
        <>
            {eventToDisplay && (
                <div className="waterfall-chart">
                    <Row style={{ marginBottom: '8px' }}>
                        <Col span={6}>
                            <div className={'color-legend'}>Event Timings</div>
                        </Col>
                        {Object.entries(eventToDisplay.pointsInTime).map(([marker, { color }]) => {
                            return (
                                <Col key={marker} span={6}>
                                    <div className={'color-legend'}>
                                        {marker}{' '}
                                        <Popover content={pointInTimeContentFor(marker)}>
                                            <span className={'color-block'} style={{ backgroundColor: color }} />
                                        </Popover>
                                    </div>
                                </Col>
                            )
                        })}
                    </Row>
                    <Row>
                        <Col span={8}>
                            {eventToDisplay.resourceTimings.map((timing) => {
                                const name = typeof timing.item === 'string' ? timing.item : timing.item.pathname
                                return (
                                    <Row key={name} className="marker-name marker-row">
                                        {name}
                                    </Row>
                                )
                            })}
                        </Col>
                        <Col span={16}>
                            {Object.entries(eventToDisplay.pointsInTime).map(([key, pointInTimeMarker]) => (
                                <VerticalMarker
                                    key={key}
                                    position={pointInTimeMarker.time}
                                    max={eventToDisplay?.maxTime}
                                    color={pointInTimeMarker.color}
                                    bringToFront={true}
                                />
                            ))}
                            {eventToDisplay.gridMarkers.map((gridMarker) => (
                                <VerticalMarker
                                    key={gridMarker}
                                    max={eventToDisplay?.maxTime}
                                    position={gridMarker}
                                    color={'var(--border-light)'}
                                />
                            ))}
                            {eventToDisplay.resourceTimings.map((resourceTiming) => {
                                const name =
                                    typeof resourceTiming.item === 'string'
                                        ? resourceTiming.item
                                        : resourceTiming.item.pathname
                                return (
                                    <Row key={name} className={'marker-row'}>
                                        <PerfBlock resourceTiming={resourceTiming} max={eventToDisplay?.maxTime} />
                                    </Row>
                                )
                            })}
                        </Col>
                    </Row>
                </div>
            )}
        </>
    )
}

const EventsWithPerformanceTable = (): JSX.Element => {
    const logic = webPerformanceLogic({ sceneUrl: urls.webPerformance() })
    const { pageViewEventsLoading, pageViewEvents, eventToDisplay } = useValues(logic)
    const { setEventToDisplay } = useActions(webPerformanceLogic)

    const columns: LemonTableColumns<EventType> = [
        {
            title: 'URL / Screen',
            key: 'url',
            render: function RenderURL(_: any, pageViewEvent: EventType) {
                let urlOrScene: { short: string; full: string }
                if (pageViewEvent.properties['$current_url']) {
                    const currentURL = pageViewEvent.properties['$current_url']
                    try {
                        const url = new URL(currentURL)
                        urlOrScene = { short: `${url.origin}${url.pathname}`, full: url.toString() }
                    } catch (e) {
                        urlOrScene = { short: currentURL, full: currentURL }
                    }
                } else {
                    urlOrScene = {
                        short: pageViewEvent.properties['$screen_name'],
                        full: pageViewEvent.properties['$screen_name'],
                    }
                }

                return (
                    <Tooltip title={urlOrScene.full}>
                        <Typography.Text style={{ width: 300 }} ellipsis={true}>
                            {urlOrScene.short}
                        </Typography.Text>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Time',
            render: function RenderTime(_: any, pageViewEvent: EventType) {
                return <TZLabel time={dayjs(pageViewEvent.timestamp)} formatString="MMMM DD, YYYY h:mm" />
            },
        },
        {
            title: 'Page Load Time',
            render: function RenderPageLoad(_: any, pageViewEvent: EventType) {
                const duration = pageViewEvent.properties['$performance_page_loaded']
                return <span>{Math.round(duration)}ms</span>
            },
        },
        {
            render: function RenderButton(_: any, pageViewEvent: EventType) {
                return (
                    <div>
                        <Button data-attr={`view-waterfall-button-${pageViewEvent.id}`} icon={<EyeOutlined />}>
                            View waterfall chart
                        </Button>
                    </div>
                )
            },
        },
    ]

    return (
        <LemonTable
            dataSource={pageViewEvents || []}
            columns={columns}
            loading={pageViewEventsLoading}
            emptyState={
                pageViewEventsLoading ? (
                    <div>Loading last ten events with performance measures</div>
                ) : (
                    <div>No events available</div>
                )
            }
            rowClassName={(pageViewEvent) => {
                return clsx({
                    'current-event': pageViewEvent.id === eventToDisplay?.id,
                    'cursor-pointer': true,
                })
            }}
            onRow={(pageViewEvent) => ({
                onClick: () => {
                    setEventToDisplay(pageViewEvent)
                },
            })}
            data-attr="waterfall-events-table"
        />
    )
}

const DebugPerfData = (): JSX.Element => {
    const { currentEvent } = useValues(webPerformanceLogic)
    return currentEvent ? (
        <Collapse>
            <Collapse.Panel header="Performance Debug Information" key="1">
                <pre>{JSON.stringify(JSON.parse(currentEvent.properties.$performance_raw), undefined, 2)}</pre>
            </Collapse.Panel>
        </Collapse>
    ) : (
        <></>
    )
}

export const WebPerformance = (): JSX.Element => {
    const logic = webPerformanceLogic({ sceneUrl: urls.webPerformance() })
    const { properties } = useValues(logic)
    const { setProperties } = useActions(logic)
    return (
        <div className="performance-waterfall">
            <PageHeader
                title={
                    <Row align="middle">
                        Web Performance
                        <LemonTag type="warning" style={{ marginLeft: 8 }}>
                            Early Preview
                        </LemonTag>
                    </Row>
                }
                caption={
                    <div>
                        <p>
                            Shows page view events where performance information has been captured. Not all events have
                            all performance information.
                        </p>
                        <p>
                            To capture performance information you must be using posthog-js and set{' '}
                            <code>_capture_performance</code> to true. See the{' '}
                            <a href="https://posthog.com/docs/integrate/client/js#config" target="_blank">
                                config instructions in our handbook
                            </a>
                        </p>
                    </div>
                }
            />
            <Row gutter={[0, 32]}>
                <Col span={24}>
                    <PropertyFilters
                        propertyFilters={properties}
                        onChange={setProperties}
                        pageKey={'web-performance-table'}
                        style={{ marginBottom: 0 }}
                        eventNames={[]}
                    />
                </Col>
                <Col span={24}>
                    <EventsWithPerformanceTable />
                </Col>
                <Col span={24}>
                    <WaterfallChart />
                </Col>
                <Col span={24}>
                    <DebugPerfData />
                </Col>
            </Row>
        </div>
    )
}

export const scene: SceneExport = {
    component: WebPerformance,
    logic: webPerformanceLogic,
    paramsToProps: () => ({ sceneUrl: urls.webPerformance() }),
}
