import { LemonBadge } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { dayjs, Dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime, pluralize } from 'lib/utils'
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
    loading?: boolean // TODO: Use this
    className?: string
}

export function TimelineSeekbar({
    points,
    selectedPointIndex,
    onPointSelection,
    from = points.length ? points[0].timestamp : dayjs(),
    to = points.length ? points[points.length - 1].timestamp : dayjs(),
    className,
}: TimelineSeekbarProps): JSX.Element {
    return (
        <div className={clsx('TimelineSeekbar', className)}>
            <div className="TimelineSeekbar__meta">
                <div className="TimelineSeekbar__note">Relevant properties over time</div>
                <div className="TimelineSeekbar__current">
                    As of{' '}
                    {selectedPointIndex !== null
                        ? humanFriendlyDetailedTime(points[selectedPointIndex].timestamp)
                        : 'now'}
                </div>
            </div>
            {points.length > 0 && (
                <div className="TimelineSeekbar__seekbar">
                    <div className="TimelineSeekbar__line">
                        <Tooltip title={`Range starts ${humanFriendlyDetailedTime(from)}`} placement="right">
                            <div className="TimelineSeekbar__line-start" />
                        </Tooltip>
                        <Tooltip title={`Range ends ${humanFriendlyDetailedTime(to)}`} placement="right">
                            <div className="TimelineSeekbar__line-end" />
                        </Tooltip>
                    </div>
                    <div className="TimelineSeekbar__points">
                        {points.map(({ timestamp, count }, index) => (
                            <Tooltip
                                key={timestamp.toISOString()}
                                title={`${humanFriendlyDetailedTime(timestamp)} • ${pluralize(count, 'such event')}`}
                                placement="bottom"
                            >
                                <div
                                    className="TimelineSeekbar__section"
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
                                    onMouseDown={() => index !== selectedPointIndex && onPointSelection(index)}
                                    onMouseEnter={
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
