import { PointInTimeMarker, ResourceTiming, webPerformanceLogic } from 'scenes/performance/webPerformanceLogic'
import { Typography } from 'antd'
import { areObjectValuesEmpty, humanFriendlyMilliseconds, humanizeBytes } from 'lib/utils'
import { ReactNode, useState } from 'react'
import { Popup } from 'lib/components/Popup/Popup'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { MultiRecordingButton } from 'scenes/session-recordings/multiRecordingButton/multiRecordingButton'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TZLabel } from 'lib/components/TZLabel'
import './WebPerformance.scss'
import { getSeriesColor } from 'lib/colors'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { IconErrorOutline, IconInfo } from 'lib/components/icons'
import { Link } from 'lib/components/Link'
import { Tooltip } from 'lib/components/Tooltip'

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
    const asResourceTiming = resourceTiming.entry
    return (
        <>
            {url && <Typography.Text type="secondary">{url}</Typography.Text>}
            <h2>
                <Typography.Text ellipsis={true}>{title}</Typography.Text>
            </h2>
            <hr />
            <p>
                started at{' '}
                {humanFriendlyMilliseconds(
                    ('start_time' in resourceTiming.entry && resourceTiming.entry.start_time) ||
                        resourceTiming.entry.fetch_start
                )}{' '}
                and took {humanFriendlyMilliseconds(resourceTiming.entry.duration)} to complete
            </p>
            {!!Object.entries(resourceTiming.performanceParts).length ? (
                <table className="performance-timings-table">
                    <thead>
                        <tr>
                            <th />
                            <th>start</th>
                            <th>end</th>
                        </tr>
                    </thead>
                    <tbody>
                        {Object.entries(resourceTiming.performanceParts).map(([key, part], index) => (
                            <tr key={index}>
                                <td className="key">{key}</td>
                                <td>{humanFriendlyMilliseconds(part.start)}</td>
                                <td>{humanFriendlyMilliseconds(part.end)}</td>
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

            {asResourceTiming.decoded_body_size !== undefined && asResourceTiming.encoded_body_size !== undefined && (
                <>
                    <hr />
                    Resource is {humanizeBytes(asResourceTiming.decoded_body_size)}
                    {asResourceTiming.encoded_body_size !== asResourceTiming.decoded_body_size && (
                        <p>
                            Was compressed. Sent {humanizeBytes(asResourceTiming.encoded_body_size)}. Saving{' '}
                            {(
                                ((asResourceTiming.decoded_body_size - asResourceTiming.encoded_body_size) /
                                    asResourceTiming.decoded_body_size) *
                                100
                            ).toFixed(1)}
                            %
                        </p>
                    )}
                </>
            )}
        </>
    )
}

const MouseTriggeredPopUp = ({ content, children }: { content: JSX.Element; children: ReactNode }): JSX.Element => {
    const [mouseIsOver, setMouseIsOver] = useState(false)

    return (
        <Popup overlay={content} visible={mouseIsOver} className="performance-popup">
            <div
                className="h-full cursor-pointer"
                onMouseEnter={() => setMouseIsOver(true)}
                onMouseLeave={() => setMouseIsOver(false)}
            >
                {children}
            </div>
        </Popup>
    )
}

export const PerfBlock = ({ resourceTiming, max }: PerfBlockProps): JSX.Element | null => {
    if (max) {
        let right = 0
        let end = 0
        let blocks: JSX.Element[]

        if (
            areObjectValuesEmpty(resourceTiming.performanceParts) &&
            resourceTiming.entry.fetch_start !== undefined &&
            resourceTiming.entry.response_end
        ) {
            const style = toPositionStyle(resourceTiming.entry.fetch_start, resourceTiming.entry.response_end, max)
            right = style?.right ?? 100
            end = resourceTiming.entry.response_end

            blocks = [
                <div
                    key={resourceTiming.entry.name}
                    className="performance-block positioned"
                    data-attr-name={resourceTiming.entry.name}
                    /* eslint-disable-next-line react/forbid-dom-props */
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
                        /* eslint-disable-next-line react/forbid-dom-props */
                        style={{ ...style?.blockSides, backgroundColor: getSeriesColor(index) }}
                    />
                )
            })
        }

        const textPosition = { left: `${100 - right + 1}%`, right: `${right}%` }
        return (
            <MouseTriggeredPopUp content={overlayFor(resourceTiming)}>
                {blocks}
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div className="positioned" style={textPosition}>
                    {humanFriendlyMilliseconds(end)}
                </div>
            </MouseTriggeredPopUp>
        )
    } else {
        return null
    }
}

const pointInTimeContent = {
    domComplete: (
        <div>
            The document and all sub-resources have finished loading. The state indicates that the load event is about
            to fire.{' '}
            <Link
                to="https://developer.mozilla.org/en-US/docs/Web/API/Document/readyState"
                disableClientSideRouting={true}
                target={'blank'}
            >
                Read more on the mozilla developer network
            </Link>
        </div>
    ),
    domInteractive: (
        <div>
            The document has finished loading and the document has been parsed but sub-resources such as scripts,
            images, stylesheets and frames are still loading.{' '}
            <Link
                to="https://developer.mozilla.org/en-US/docs/Web/API/Document/readyState"
                disableClientSideRouting={true}
                target={'blank'}
            >
                Read more on the mozilla developer network
            </Link>
        </div>
    ),
    pageLoaded: (
        <div>
            The load event is fired when the whole page has loaded, including all dependent resources such as
            stylesheets and images. This is in contrast to DOMContentLoaded, which is fired as soon as the page DOM has
            been loaded, without waiting for resources to finish loading.{' '}
            <Link
                to="https://developer.mozilla.org/en-US/docs/Web/API/Window/load_event"
                disableClientSideRouting={true}
                target={'blank'}
            >
                Read more on the mozilla developer network
            </Link>
        </div>
    ),
    'first-contentful-paint': (
        <div>
            First Contentful Paint (FCP) is when the browser renders the first bit of content from the DOM, providing
            the first feedback to the user that the page is actually loading.{' '}
            <Link
                to="https://developer.mozilla.org/en-US/docs/Glossary/First_contentful_paint"
                disableClientSideRouting={true}
                target={'blank'}
            >
                Read more on the mozilla developer network
            </Link>
        </div>
    ),
    'first-paint': (
        <div>
            First Paint is the time between navigation and when the browser first renders pixels to the screen,
            rendering anything that is visually different from the default background color of the body. It is the first
            key moment in page load and will answer the question "Has the browser started to render the page?"{' '}
            <Link
                to="https://developer.mozilla.org/en-US/docs/Glossary/First_paint"
                disableClientSideRouting={true}
                target={'blank'}
            >
                Read more on the mozilla developer network
            </Link>
        </div>
    ),
}

const pointInTimeContentFor = (pointInTimeMarker: string): JSX.Element =>
    pointInTimeContent[pointInTimeMarker] ?? <div>Unknown marker: {pointInTimeMarker}</div>

const VerticalMarker = ({
    marker,
    max,
    position,
    color,
    bringToFront,
}: {
    marker?: string
    max: number | undefined
    position: number
    color: string
    bringToFront?: boolean
}): JSX.Element | null => {
    const { highlightedPointInTime } = useValues(webPerformanceLogic)

    if (max) {
        const left = (position / max) * 100

        return (
            <div
                className={clsx('VerticalMarker', {
                    'VerticalMarker__in-front': bringToFront,
                    VerticalMarker__hidden: !!marker && marker !== highlightedPointInTime,
                    VerticalMarker__highlighted: !!marker && marker === highlightedPointInTime,
                })}
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{ left: `${left}%`, backgroundColor: color }}
            />
        )
    } else {
        return null
    }
}

function PointsInTime(props: { pointsInTime: PointInTimeMarker[] }): JSX.Element {
    const { highlightPointInTime } = useActions(webPerformanceLogic)
    return (
        <div className={'flex flex-row gap-1 justify-around flex-wrap p-4 justify-center items-center'}>
            {props.pointsInTime.map(({ marker, color, time }) => {
                return (
                    <div key={marker} className={'min-w-1/5'}>
                        <div
                            className={'flex flex-col pointer border rounded mb-2 cursor-pointer'}
                            /* eslint-disable-next-line react/forbid-dom-props */
                            style={{ borderColor: color }}
                            onMouseEnter={() => highlightPointInTime(marker)}
                            onMouseLeave={() => highlightPointInTime(null)}
                        >
                            <div className={'p-2 flex flex-row items-center gap-1 self-center'}>
                                {marker}
                                <Tooltip title={pointInTimeContentFor(marker)} placement="top">
                                    <IconInfo />
                                </Tooltip>
                            </div>
                            <div
                                className={'color-block text-white min-w-8 text-center'}
                                /* eslint-disable-next-line react/forbid-dom-props */
                                style={{ backgroundColor: color }}
                            >
                                {humanFriendlyMilliseconds(time)}
                            </div>
                        </div>
                    </div>
                )
            })}
        </div>
    )
}

function ResourceTimingsNames(props: { timings: ResourceTiming[] }): JSX.Element {
    return (
        <>
            {props.timings.map((timing) => {
                const name = typeof timing.item === 'string' ? timing.item : timing.item.pathname
                return (
                    <div
                        key={timing.entry.uuid}
                        className={'pl-1 marker-row marker-name flex flex-row w-full items-center'}
                    >
                        <span className={'w-full overflow-x-auto whitespace-nowrap'}>{name}</span>
                    </div>
                )
            })}
        </>
    )
}

function ResourceTimingSpans(props: { timings: ResourceTiming[]; maxTime: number }): JSX.Element {
    return (
        <>
            {props.timings.map((timing) => {
                return (
                    <div key={timing.entry.uuid} className={'relative'}>
                        <div className={'marker-row'}>
                            <PerfBlock resourceTiming={timing} max={props.maxTime} />
                        </div>
                    </div>
                )
            })}
        </>
    )
}

function EventMarkers(props: { markers: PointInTimeMarker[]; maxTime: number }): JSX.Element {
    return (
        <>
            {props.markers.map(({ marker, time, color }) => (
                <VerticalMarker
                    key={marker}
                    marker={marker}
                    position={time}
                    max={props.maxTime}
                    color={color}
                    bringToFront={true}
                />
            ))}
        </>
    )
}

function ScaleMarkers(props: { markers: number[]; maxTime: number }): JSX.Element {
    return (
        <>
            {props.markers.map((gridMarker) => (
                <VerticalMarker
                    key={gridMarker}
                    max={props.maxTime}
                    position={gridMarker}
                    color={'var(--border-light)'}
                />
            ))}
        </>
    )
}

export function WebPerformanceWaterfallChart(): JSX.Element {
    const { pageviewEventsLoading, pageviewEventsFailed, waterfallData, sessionRecording } =
        useValues(webPerformanceLogic)
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)

    return (
        <>
            {pageviewEventsLoading ? (
                <div className={'w-full h-full flex flex-row gap-2 justify-center items-center'}>
                    <Spinner className={'text-2xl'} />
                    <h1 className={'m-0'}>Loading performance data</h1>
                </div>
            ) : pageviewEventsFailed ? (
                <div className={'w-full h-full flex flex-row gap-2 justify-center items-center'}>
                    <IconErrorOutline className="text-2xl" />
                    <h1 className={'m-0'}>There was an unexpected error loading this page's performance events</h1>
                </div>
            ) : (
                <div className={'w-full h-full flex flex-col gap-2 justify-center items-center'}>
                    <div className={'flex flex-row w-full justify-between items-center'}>
                        <h1 className="chart-title">
                            <PropertyKeyInfo value={'$pageview'} />
                            ,&nbsp;
                            <TZLabel time={waterfallData.timestamp} />
                        </h1>

                        <MultiRecordingButton
                            sessionRecordings={sessionRecording}
                            onOpenRecording={(matchedRecording) => {
                                matchedRecording?.session_id && openSessionPlayer({ id: matchedRecording.session_id })
                            }}
                        />
                        <SessionPlayerModal />
                    </div>
                    <div className="py-4 min-h-16 border-t w-full">
                        <div className="border rounded p-4 waterfall-chart">
                            <PointsInTime pointsInTime={waterfallData.pointsInTime} />
                            <div className={'flex flex-row'}>
                                <div className={'w-1/3'}>
                                    <ResourceTimingsNames timings={waterfallData.resourceTimings} />
                                </div>
                                <div className={'w-2/3 relative'}>
                                    <EventMarkers
                                        markers={waterfallData.pointsInTime}
                                        maxTime={waterfallData.maxTime}
                                    />
                                    <ScaleMarkers markers={waterfallData.gridMarkers} maxTime={waterfallData.maxTime} />
                                    <ResourceTimingSpans
                                        timings={waterfallData.resourceTimings}
                                        maxTime={waterfallData.maxTime}
                                    />
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </>
    )
}
