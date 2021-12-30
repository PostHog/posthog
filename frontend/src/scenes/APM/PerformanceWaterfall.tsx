import React from 'react'
import { Col, Row } from 'antd'
import './PerformanceWaterfall.scss'

const event = {
    properties: {
        $performance_dnsLookupTime: { start: 0, end: 3 },
        $performance_connectionTime: { start: 3, end: 10 },
        $performance_tlsTime: { start: 4, end: 6 },
        $performance_domContentLoaded: { start: 42, end: 42 },
        $performance_fetchTime: { start: 40, end: 46 },
        $performance_timeToFirstByte: { start: 15, end: 40 },
    },
}

const performanceProperties = Object.entries(event.properties).filter(([key]) => key.startsWith('$performance'))

const perfDisplay = performanceProperties
    .filter((entry) => entry[1].start !== entry[1].end)
    .sort((a, b) => {
        return a[1].start - b[1].start
    })

const lastMarker = perfDisplay[perfDisplay.length - 1]
const lastMarkerEnd = lastMarker[1].end

const pointsInTime = performanceProperties.filter((entry) => entry[1].start === entry[1].end)

const minorGridStep = lastMarkerEnd / 10
const gridMarkers = Array.from(Array(10).keys()).map((n) => n * minorGridStep)

interface PerfBlockProps {
    start: number
    end: number
    max: number
}

function PerfBlock({ start, end, max }: PerfBlockProps): JSX.Element {
    const left = (start / max) * 100
    const right = 100 - (end / max) * 100
    const blockSides = { left: `${left}%`, right: `${right}%` }
    return (
        <>
            <div className="performance-block positioned" style={blockSides} />
            <div className="positioned" style={{ left: `${100 - right + 1}%`, right: `${right}%` }}>
                {end}ms
            </div>
        </>
    )
}

function VerticalMarker({ max, position, color }: { max: number; position: number; color: string }): JSX.Element {
    const left = (position / max) * 100
    return <div className="vertical-marker" style={{ left: `${left}%`, backgroundColor: color }} />
}

export function PerformanceWaterfall(): JSX.Element {
    return (
        <div className="apm-performance-waterfall">
            <Row>
                <Col span={8}>
                    {perfDisplay.map(([marker]) => {
                        return (
                            <Row key={marker} className="marker-name marker-row">
                                {marker}
                            </Row>
                        )
                    })}
                </Col>
                <Col span={16}>
                    {pointsInTime.map((pit) => (
                        <VerticalMarker key={pit[0]} position={pit[1].start} max={lastMarkerEnd} color={'red'} />
                    ))}
                    {gridMarkers.map((gridMarker) => (
                        <VerticalMarker
                            key={gridMarker}
                            max={lastMarkerEnd}
                            position={gridMarker}
                            color={'var(--border-light)'}
                        />
                    ))}
                    {perfDisplay.map(([marker, times]) => (
                        <Row key={marker} className={'marker-row'}>
                            <PerfBlock start={times.start} end={times.end} max={lastMarkerEnd} />
                        </Row>
                    ))}
                </Col>
            </Row>
        </div>
    )
}
