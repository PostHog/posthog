import './TimelineSeekbar.scss'

import clsx from 'clsx'

import { LemonBadge } from '@posthog/lemon-ui'

import { Dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDetailedTime, pluralize } from 'lib/utils'

export interface TimelinePoint {
    timestamp: Dayjs
    count: number
}

export interface TimelineSeekbarProps {
    points: TimelinePoint[]
    note: JSX.Element | string
    selectedPointIndex: number | null
    onPointSelection: (index: number | null) => void
    dateRange: [Dayjs, Dayjs] | null
    loading?: boolean
    className?: string
}

export function TimelineSeekbar({
    points,
    note,
    selectedPointIndex,
    onPointSelection,
    dateRange,
    loading,
    className,
}: TimelineSeekbarProps): JSX.Element {
    const selectedPoint: TimelinePoint | undefined =
        selectedPointIndex !== null ? points[selectedPointIndex] : undefined

    return (
        <div className={clsx('TimelineSeekbar', className)}>
            <div className="TimelineSeekbar__meta">
                <div className="TimelineSeekbar__note">
                    {note}
                    {loading && <Spinner className="ml-1 text-xl" />}
                </div>
                <div className="TimelineSeekbar__current">
                    As of {selectedPoint ? humanFriendlyDetailedTime(selectedPoint.timestamp) : 'now'}
                </div>
            </div>
            {points.length > 0 && (
                <div className="TimelineSeekbar__seekbar">
                    <div className="TimelineSeekbar__line">
                        <Tooltip
                            title={
                                dateRange ? (
                                    <span>
                                        This data point's range starts at
                                        <br />
                                        {humanFriendlyDetailedTime(dateRange[0])}
                                    </span>
                                ) : (
                                    "This data point's range hasn't been loaded yet"
                                )
                            }
                            placement="top-start"
                            offset={0}
                            delayMs={0}
                        >
                            <div className="TimelineSeekbar__line-start" />
                        </Tooltip>
                        <Tooltip
                            title={
                                dateRange ? (
                                    <>
                                        <p>
                                            This data point's range ends at
                                            <br />
                                            {humanFriendlyDetailedTime(dateRange[1])}
                                        </p>
                                        <em>Click to view properties as they are in the present</em>
                                    </>
                                ) : (
                                    "This data point's range hasn't been loaded yet"
                                )
                            }
                            placement="top-end"
                            offset={0}
                            delayMs={0}
                        >
                            <div
                                className="TimelineSeekbar__line-end"
                                onMouseDown={(e) =>
                                    e.button === 0 && selectedPointIndex !== null && onPointSelection(null)
                                }
                                onMouseOver={(e) =>
                                    e.buttons === 1 && selectedPointIndex !== null && onPointSelection(null)
                                }
                            />
                        </Tooltip>
                    </div>
                    <div className="TimelineSeekbar__points">
                        {dateRange &&
                            points.map(({ timestamp, count }, index) => (
                                <Tooltip
                                    key={timestamp.toISOString()}
                                    title={
                                        <span className="text-center">
                                            Starting {humanFriendlyDetailedTime(timestamp)}
                                            <br />
                                            {pluralize(count, 'relevant event')} with such properties
                                        </span>
                                    }
                                    placement="top-start"
                                    arrowOffset={7}
                                    delayMs={0}
                                >
                                    <div
                                        className="TimelineSeekbar__section"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={
                                            {
                                                '--timeline-seekbar-section-progress-current': `${
                                                    (timestamp.diff(dateRange[0], 'ms') /
                                                        dateRange[1].diff(dateRange[0], 'ms')) *
                                                    100
                                                }%`,
                                                '--timeline-seekbar-section-progress-next': `${
                                                    ((points[index + 1]?.timestamp || dateRange[1]).diff(
                                                        timestamp,
                                                        'ms'
                                                    ) /
                                                        dateRange[1].diff(dateRange[0], 'ms')) *
                                                    100
                                                }%`,
                                            } as React.CSSProperties
                                        }
                                        /** Simulate slider-like behavior with mousedown and mouseenter. */
                                        onMouseDown={(e) =>
                                            // e.button === 0 means that the left mouse button was pressed
                                            e.button === 0 && index !== selectedPointIndex && onPointSelection(index)
                                        }
                                        // For some reason Tooltip blocks onMouseEnter here, but onMouseOver works
                                        onMouseOver={
                                            // e.buttons === 1 means that the left mouse button, and only that one, must be pressed
                                            (e) =>
                                                e.buttons === 1 &&
                                                index !== selectedPointIndex &&
                                                onPointSelection(index)
                                        }
                                    >
                                        <LemonBadge.Number
                                            count={count}
                                            size="small"
                                            active={index === selectedPointIndex}
                                            maxDigits={Infinity}
                                        />
                                    </div>
                                </Tooltip>
                            ))}
                    </div>
                </div>
            )}
        </div>
    )
}
