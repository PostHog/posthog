import React from 'react'
import { Button, Col, Row, Space, Typography } from 'antd'
import './PerformanceWaterfall.scss'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PageHeader } from 'lib/components/PageHeader'
import clsx from 'clsx'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { EventType } from '~/types'
import { TZLabel } from 'lib/components/TimezoneAware'
import { EyeOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { Tooltip } from 'lib/components/Tooltip'
import { useActions, useValues } from 'kea'
import { apmLogic } from 'scenes/APM/apmLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

interface PerfBlockProps {
    start: number
    end: number
    max: number | undefined
}

function PerfBlock({ start, end, max }: PerfBlockProps): JSX.Element {
    if (max) {
        const left = (start / max) * 100
        const right = 100 - (end / max) * 100
        const blockSides = { left: `${left}%`, right: `${right}%` }
        const textPosition = { left: `${100 - right + 1}%`, right: `${right}%` }
        return (
            <>
                <div className="performance-block positioned" style={blockSides} />
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
    const { eventToDisplay } = useValues(apmLogic)
    return (
        <>
            {eventToDisplay && (
                <div className="waterfall-chart">
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
                            {Object.entries(eventToDisplay.pointsInTime).map(([key, time]) => (
                                <Tooltip title={key} key={key}>
                                    <VerticalMarker
                                        position={time}
                                        max={eventToDisplay?.maxTime}
                                        color={'red'}
                                        bringToFront={true}
                                    />
                                </Tooltip>
                            ))}
                            {eventToDisplay.gridMarkers.map((gridMarker) => (
                                <VerticalMarker
                                    key={gridMarker}
                                    max={eventToDisplay?.maxTime}
                                    position={gridMarker}
                                    color={'var(--border-light)'}
                                />
                            ))}
                            {Object.entries(eventToDisplay.durations).map(([marker, times]) => (
                                <Row key={marker} className={'marker-row'}>
                                    <PerfBlock start={times.start} end={times.end} max={eventToDisplay?.maxTime} />
                                </Row>
                            ))}
                        </Col>
                    </Row>
                </div>
            )}
        </>
    )
}

function EventsWithPerformanceTable(): JSX.Element {
    const { pageViewEventsLoading, pageViewEvents } = useValues(apmLogic)
    const { setEventToDisplay } = useActions(apmLogic)
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
                const duration = pageViewEvent.properties['$performance_pageLoaded']
                return <span>{Math.round(duration)}ms</span>
            },
        },
        {
            render: function RenderPlayButton(_: any, pageViewEvent: EventType) {
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
            onRow={(pageViewEvent) => ({
                onClick: () => {
                    setEventToDisplay(pageViewEvent)
                },
            })}
            rowClassName="cursor-pointer"
            data-attr="apm-waterfall-events-table"
        />
    )
}

export function PerformanceWaterfall(): JSX.Element {
    return (
        <div className="apm-performance-waterfall">
            <PageHeader
                title={
                    <Row align="middle">
                        Web Performance
                        <LemonTag type="warning" style={{ marginLeft: 8 }}>
                            Beta
                        </LemonTag>
                    </Row>
                }
            />
            <Space direction="vertical">
                <EventsWithPerformanceTable />
                <WaterfallChart />
            </Space>
        </div>
    )
}

export const scene: SceneExport = {
    component: PerformanceWaterfall,
    logic: apmLogic,
    paramsToProps: () => ({ sceneUrl: urls.apm() }),
}
