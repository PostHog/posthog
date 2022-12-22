import { LemonBadge } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { dayjs, Dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime, pluralize } from 'lib/utils'
import { AlignType } from 'rc-trigger/lib/interface'
import { Spinner } from '../Spinner/Spinner'
import { Tooltip } from '../Tooltip'
import './TimelineSeekbar.scss'

export interface TimelinePoint {
    timestamp: Dayjs
    count: number
}

export interface TimelineSeekbarProps {
    points: TimelinePoint[]
    selectedPointIndex: number | null
    onPointSelection: (index: number) => void
    from?: Dayjs
    to?: Dayjs
    loading?: boolean
    className?: string
}

const SEEKBAR_TOOLTIP_PLACEMENTS: Record<string, AlignType> = {
    topRight: {
        points: ['br', 'tr'],
        offset: [7, 0], // To align with badges
        overflow: {
            adjustX: 0,
            adjustY: 0,
        },
    },
    topLeft: {
        points: ['bl', 'tl'],
        offset: [-7, 0], // To align with badges
        overflow: {
            adjustX: 0,
            adjustY: 0,
        },
    },
}

export function TimelineSeekbar({
    points,
    selectedPointIndex,
    onPointSelection,
    from = points.length ? points[0].timestamp : dayjs(),
    to = points.length ? points[points.length - 1].timestamp : dayjs(),
    loading,
    className,
}: TimelineSeekbarProps): JSX.Element {
    return (
        <div className={clsx('TimelineSeekbar', className)}>
            <div className="TimelineSeekbar__meta">
                <div className="TimelineSeekbar__note">Relevant properties over time</div>
                <div className="TimelineSeekbar__current">
                    {loading && <Spinner monocolor />}
                    <span>
                        As of{' '}
                        {selectedPointIndex !== null
                            ? humanFriendlyDetailedTime(points[selectedPointIndex].timestamp)
                            : 'now'}
                    </span>
                </div>
            </div>
            {points.length > 0 && (
                <div className="TimelineSeekbar__seekbar">
                    <div className="TimelineSeekbar__line">
                        <Tooltip
                            title={
                                <span>
                                    This data point's range starts at
                                    <br />
                                    {humanFriendlyDetailedTime(from)}
                                </span>
                            }
                            placement="topLeft"
                            builtinPlacements={SEEKBAR_TOOLTIP_PLACEMENTS}
                            delayMs={0}
                        >
                            <div className="TimelineSeekbar__line-start" />
                        </Tooltip>
                        <Tooltip
                            title={
                                <span>
                                    This data point's range ends at
                                    <br />
                                    {humanFriendlyDetailedTime(to)}
                                </span>
                            }
                            placement="topRight"
                            builtinPlacements={SEEKBAR_TOOLTIP_PLACEMENTS}
                            delayMs={0}
                        >
                            <div className="TimelineSeekbar__line-end" />
                        </Tooltip>
                    </div>
                    <div className="TimelineSeekbar__points">
                        {points.map(({ timestamp, count }, index) => (
                            <Tooltip
                                key={timestamp.toISOString()}
                                title={
                                    <span className="text-center">
                                        Starting {humanFriendlyDetailedTime(timestamp)}
                                        <br />
                                        {pluralize(count, 'relevant event')} with such properties
                                    </span>
                                }
                                placement="topLeft"
                                builtinPlacements={SEEKBAR_TOOLTIP_PLACEMENTS}
                                delayMs={0}
                            >
                                <div
                                    className="TimelineSeekbar__section"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={
                                        {
                                            '--timeline-seekbar-section-progress-current': `${
                                                (timestamp.diff(from, 'ms') / to.diff(from, 'ms')) * 100
                                            }%`,
                                            '--timeline-seekbar-section-progress-next': `${
                                                ((points[index + 1]?.timestamp || to).diff(timestamp, 'ms') /
                                                    to.diff(from, 'ms')) *
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
                                            e.buttons === 1 && index !== selectedPointIndex && onPointSelection(index)
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
