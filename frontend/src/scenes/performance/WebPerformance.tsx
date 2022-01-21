import React from 'react'
import { Button, Col, Row, Typography } from 'antd'
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
import { webPerformanceLogic } from 'scenes/performance/webPerformanceLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

interface PerfBlockProps {
    start: number
    end: number
    max: number | undefined
    color?: string
}

function PerfBlock({ start, end, max, color }: PerfBlockProps): JSX.Element {
    if (max) {
        const left = (start / max) * 100
        const right = 100 - (end / max) * 100
        const blockSides = { left: `${left}%`, right: `${right}%` }
        const textPosition = { left: `${100 - right + 1}%`, right: `${right}%` }
        return (
            <>
                <div className="performance-block positioned" style={{ ...blockSides, backgroundColor: color }} />
                <div className="positioned" style={textPosition}>
                    {Math.round(end)}ms
                </div>
            </>
        )
    } else {
        return <></>
    }
}

function VerticalMarker({
    max,
    position,
    color,
    bringToFront,
}: {
    max: number | undefined
    position: number
    color: string
    bringToFront?: boolean
}): JSX.Element {
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

function WaterfallChart(): JSX.Element {
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
                                        {marker} <span className={'color-block'} style={{ backgroundColor: color }} />
                                    </div>
                                </Col>
                            )
                        })}
                    </Row>
                    <Row>
                        <Col span={8}>
                            {Object.entries(eventToDisplay.durations).map(([marker]) => {
                                return (
                                    <Row key={marker} className="marker-name marker-row">
                                        {marker}
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
                            {Object.entries(eventToDisplay.durations).map(([marker, measure]) => {
                                return (
                                    <Row key={marker} className={'marker-row'}>
                                        <PerfBlock
                                            start={measure.start}
                                            end={measure.end}
                                            max={eventToDisplay?.maxTime}
                                            color={measure.color}
                                        />
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

function EventsWithPerformanceTable(): JSX.Element {
    const { pageViewEventsLoading, pageViewEvents, eventToDisplay } = useValues(webPerformanceLogic)
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

function DebugPerfData(): JSX.Element {
    const { currentEvent } = useValues(webPerformanceLogic)
    return (
        <pre>
            {currentEvent ? JSON.stringify(JSON.parse(currentEvent.properties.$performance_raw), undefined, 2) : null}
        </pre>
    )
}

export function WebPerformance(): JSX.Element {
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
            />
            <Row gutter={[0, 32]}>
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
