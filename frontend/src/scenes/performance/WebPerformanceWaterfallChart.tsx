import {
    MinimalPerformanceResourceTiming,
    ResourceTiming,
    webPerformanceLogic,
} from 'scenes/performance/webPerformanceLogic'
import { Col, Collapse, Row, Typography } from 'antd'
import { areObjectValuesEmpty, humanizeBytes } from 'lib/utils'
import React, { useState } from 'react'
import { Popup } from 'lib/components/Popup/Popup'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { MultiRecordingButton } from 'scenes/session-recordings/multiRecordingButton/multiRecordingButton'
import { SessionPlayerDrawer } from 'scenes/session-recordings/SessionPlayerDrawer'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TZLabel } from 'lib/components/TimezoneAware'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import './WebPerformance.scss'
import Text from 'antd/lib/typography/Text'
import { getSeriesColor } from 'lib/colors'

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

const overlayFor = (resourceTiming: ResourceTiming): JSX.Element => {
    const title = typeof resourceTiming.item == 'string' ? resourceTiming.item : resourceTiming.item.pathname
    const url = typeof resourceTiming.item == 'string' ? null : resourceTiming.item.host
    const asResourceTiming = resourceTiming.entry as PerformanceResourceTiming
    return (
        <>
            {url && <Typography.Text type="secondary">{url}</Typography.Text>}
            <h2>
                <Typography.Text ellipsis={true}>{title}</Typography.Text>
            </h2>
            <hr />
            <p>
                started at {resourceTiming.entry.startTime || resourceTiming.entry.fetchStart}ms and took{' '}
                {resourceTiming.entry.duration}ms to complete
            </p>
            {Object.entries(resourceTiming.performanceParts).length ? (
                <table className="performance-timings-table">
                    <thead>
                        <tr>
                            <th />
                            <th>start (ms)</th>
                            <th>end (ms)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {Object.entries(resourceTiming.performanceParts).map(([key, part], index) => (
                            <tr key={index}>
                                <td className="key">{key}</td>
                                <td>{part.start}</td>
                                <td>{part.end}</td>
                                <td>
                                    {resourceTiming.entry.duration ? (
                                        <>
                                            {(((part.end - part.start) / resourceTiming.entry.duration) * 100).toFixed(
                                                1
                                            )}
                                            %
                                        </>
                                    ) : null}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            ) : null}

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

const MouseTriggeredPopUp = ({
    content,
    children,
}: {
    content: JSX.Element
    children: React.ReactNode
}): JSX.Element => {
    const [mouseIsOver, setMouseIsOver] = useState(false)

    return (
        <Popup overlay={content} visible={mouseIsOver} className="performance-popup">
            <div
                onMouseEnter={() => setMouseIsOver(true)}
                onMouseLeave={() => setMouseIsOver(false)}
                style={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}
            >
                {children}
            </div>
        </Popup>
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
                        style={{ ...style?.blockSides, backgroundColor: getSeriesColor(index) }}
                    />
                )
            })
        }

        const textPosition = { left: `${100 - right + 1}%`, right: `${right}%` }
        return (
            <MouseTriggeredPopUp content={overlayFor(resourceTiming)}>
                {blocks}
                <div className="positioned" style={textPosition}>
                    {Math.round(end)}ms
                </div>
            </MouseTriggeredPopUp>
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
    firstContentfulPaint: (
        <div>
            First Contentful Paint (FCP) is when the browser renders the first bit of content from the DOM, providing
            the first feedback to the user that the page is actually loading.{' '}
            <a href="https://developer.mozilla.org/en-US/docs/Glossary/First_contentful_paint" target="_blank">
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

function WaterfallChart(): JSX.Element {
    const { eventToDisplay, openedSessionRecordingId, currentEvent, sessionRecording } = useValues(webPerformanceLogic)
    const { openRecordingModal, closeRecordingModal } = useActions(webPerformanceLogic)
    return (
        <>
            {currentEvent && (
                <>
                    <Row>
                        <Col span={24}>
                            <h1 className="chart-title">
                                <PropertyKeyInfo value={'$pageview'} />
                                ,&nbsp;
                                <TZLabel time={currentEvent.timestamp} />
                                ,&nbsp;by&nbsp;
                                <PersonHeader person={currentEvent.person} />
                            </h1>
                        </Col>
                    </Row>
                    <Row>
                        <Col span={24} className="control-row">
                            <div style={{ textAlign: 'right' }}>
                                <MultiRecordingButton
                                    sessionRecordings={sessionRecording}
                                    onOpenRecording={(matchedRecording) => {
                                        openRecordingModal(matchedRecording.session_id)
                                    }}
                                />
                            </div>
                        </Col>
                    </Row>
                </>
            )}
            {!!openedSessionRecordingId && <SessionPlayerDrawer onClose={closeRecordingModal} />}
            {eventToDisplay && (
                <Row data-tooltip="web-performance-chart">
                    <Col span={24}>
                        <div className="waterfall-chart">
                            <Row style={{ marginBottom: '8px' }}>
                                {Object.entries(eventToDisplay.pointsInTime).map(([marker, { color }]) => {
                                    return (
                                        <Col key={marker} span={6}>
                                            <div className={'color-legend'}>
                                                <MouseTriggeredPopUp content={pointInTimeContentFor(marker)}>
                                                    {marker}{' '}
                                                    <span
                                                        className={'color-block'}
                                                        style={{ backgroundColor: color }}
                                                    />
                                                </MouseTriggeredPopUp>
                                            </div>
                                        </Col>
                                    )
                                })}
                            </Row>
                            <Row>
                                <Col span={8}>
                                    {eventToDisplay.resourceTimings.map((timing) => {
                                        const name =
                                            typeof timing.item === 'string' ? timing.item : timing.item.pathname
                                        return (
                                            <Row key={name} className="marker-name marker-row">
                                                <Text ellipsis={true} title={name}>
                                                    {name}
                                                </Text>
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
                                                <PerfBlock
                                                    resourceTiming={resourceTiming}
                                                    max={eventToDisplay?.maxTime}
                                                />
                                            </Row>
                                        )
                                    })}
                                </Col>
                            </Row>
                        </div>
                    </Col>
                </Row>
            )}
        </>
    )
}

const DebugPerfData = (): JSX.Element | null => {
    const { currentEvent } = useValues(webPerformanceLogic)
    return currentEvent ? (
        <Collapse>
            <Collapse.Panel header="Performance Debug Information" key="1">
                <pre>{JSON.stringify(JSON.parse(currentEvent.properties.$performance_raw), undefined, 2)}</pre>
            </Collapse.Panel>
        </Collapse>
    ) : null
}

export function WebPerformanceWaterfallChart(): JSX.Element {
    return (
        <Row gutter={[0, 32]}>
            <Col span={24}>
                <WaterfallChart />
            </Col>
            <Col span={24}>
                <DebugPerfData />
            </Col>
        </Row>
    )
}
