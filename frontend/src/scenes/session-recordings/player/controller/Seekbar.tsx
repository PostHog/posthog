import './Seekbar.scss'

import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { cn } from 'lib/utils/css-classes'
import { MutableRefObject, useEffect, useMemo, useRef } from 'react'
import React from 'react'

import useIsHovering from '~/lib/hooks/useIsHovering'
import { RecordingSegment } from '~/types'

import { playerInspectorLogic } from '../inspector/playerInspectorLogic'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingDataLogic } from '../sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSeekbarPreview } from './PlayerSeekbarPreview'
import { PlayerSeekbarTicks } from './PlayerSeekbarTicks'
import { seekbarLogic } from './seekbarLogic'

// the seekbar and its children can be accidentally re-rendered as the player ticks
const SeekbarSegment = React.memo(function SeekbarSegmentRaw({
    segment,
    durationMs,
}: {
    segment: RecordingSegment
    durationMs: number
}): JSX.Element {
    return (
        <div
            className={clsx(
                'PlayerSeekbar__segments__item',
                segment.isActive && 'PlayerSeekbar__segments__item--active'
            )}
            title={!segment.isActive ? 'Inactive period' : 'Active period'}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: `${(100 * segment.durationMs) / durationMs}%`,
            }}
        />
    )
})

function SeekbarSegments(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { segments, durationMs } = useValues(sessionRecordingDataLogic(logicProps))
    return (
        <div className="PlayerSeekbar__segments">
            {segments?.map((segment: RecordingSegment) => (
                <SeekbarSegment
                    segment={segment}
                    durationMs={durationMs}
                    key={`${segment.startTimestamp}-${segment.endTimestamp}-${segment.windowId}-${segment.kind}`}
                />
            ))}
        </div>
    )
}

interface ActivityPoint {
    second: number
    x: number
    y: number
}

export function UserActivity({ hoverRef }: { hoverRef: MutableRefObject<HTMLDivElement | null> }): JSX.Element {
    const { activityPerSecond, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { endTimeMs: durationMs } = useValues(seekbarLogic(logicProps))

    const seekBarRef = useRef<HTMLDivElement | null>(null)
    const [width, height] = useSize(seekBarRef)
    const durationInSeconds = durationMs / 1000

    const isHovering = useIsHovering(hoverRef)

    const points: ActivityPoint[] = useMemo(() => {
        const maxY = Math.max(...Object.values(activityPerSecond).map((activity) => activity.y))

        // Convert to array and sort by second for easier neighbor access
        const sortedPoints = Object.entries(activityPerSecond).map(([second, activity]) => ({
            second: parseInt(second),
            ...activity,
        }))

        // Wider spread with 15 points - affects ±7 seconds
        const weights = [
            0.02,
            0.03,
            0.04,
            0.06,
            0.08,
            0.1,
            0.13,
            0.2, // center point
            0.13,
            0.1,
            0.08,
            0.06,
            0.04,
            0.03,
            0.02,
        ]

        return sortedPoints.map((point, index) => {
            let smoothedY = 0
            for (let i = -7; i <= 7; i++) {
                const neighborIndex = index + i
                if (neighborIndex >= 0 && neighborIndex < sortedPoints.length) {
                    smoothedY += (sortedPoints[neighborIndex].y || 0) * weights[i + 7]
                }
            }

            return {
                second: point.second,
                x: (point.second / durationInSeconds) * width,
                y: height - (Math.log(smoothedY + 1) / Math.log(maxY + 1)) * height,
            }
        })
    }, [activityPerSecond, durationInSeconds, width, height])

    return (
        <div
            className={cn('absolute bottom-0 w-full bg-surface-primary transition-opacity duration-300', {
                'opacity-0': !isHovering,
            })}
            ref={seekBarRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: '3rem' }}
        >
            <svg width="100%" height="100%" preserveAspectRatio="none">
                {/* DOM Mutations - Medium opacity */}
                <path
                    d={
                        points.length
                            ? `
                        M 0,${height}
                        ${points.map((point) => `L ${point.x},${point.y}`).join(' ')}
                        L ${width},${height}
                        Z
                    `
                            : ''
                    }
                    fill="var(--bg-fill-highlight-200)"
                    stroke="none"
                />
            </svg>
        </div>
    )
}

export function Seekbar(): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)
    const { seekbarItems } = useValues(playerInspectorLogic(logicProps))
    const { endTimeMs, thumbLeftPos, bufferPercent, isScrubbing } = useValues(seekbarLogic(logicProps))
    const { timestampFormat } = useValues(playerSettingsLogic)

    const { handleDown, setSlider, setThumb } = useActions(seekbarLogic(logicProps))
    const { sessionPlayerData, sessionPlayerMetaData } = useValues(sessionRecordingDataLogic(logicProps))

    const sliderRef = useRef<HTMLDivElement | null>(null)
    const thumbRef = useRef<HTMLDivElement | null>(null)
    const seekBarRef = useRef<HTMLDivElement | null>(null)

    // Workaround: Something with component and logic mount timing that causes slider and thumb
    // reducers to be undefined.
    useEffect(() => {
        if (sliderRef.current && thumbRef.current) {
            setSlider(sliderRef)
            setThumb(thumbRef)
        }
    }, [sliderRef.current, thumbRef.current, sessionRecordingId])

    return (
        <div className="flex flex-col items-end h-8 mx-4 mt-2" data-attr="rrweb-controller">
            <PlayerSeekbarTicks
                seekbarItems={seekbarItems}
                endTimeMs={endTimeMs}
                seekToTime={seekToTime}
                hoverRef={seekBarRef}
            />

            <div className={clsx('PlayerSeekbar', { 'PlayerSeekbar--scrubbing': isScrubbing })} ref={seekBarRef}>
                <div
                    className="PlayerSeekbar__slider"
                    ref={sliderRef}
                    onMouseDown={handleDown}
                    onTouchStart={handleDown}
                >
                    <SeekbarSegments />

                    <div
                        className="PlayerSeekbar__currentbar"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${Math.max(thumbLeftPos, 0)}px` }}
                    />
                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <div className="PlayerSeekbar__bufferbar" style={{ width: `${bufferPercent}%` }} />
                    <div
                        className="PlayerSeekbar__thumb"
                        ref={thumbRef}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ transform: `translateX(${thumbLeftPos}px)` }}
                    />

                    <PlayerSeekbarPreview
                        minMs={0}
                        maxMs={sessionPlayerData.durationMs}
                        seekBarRef={seekBarRef}
                        activeMs={
                            sessionPlayerMetaData?.active_seconds ? sessionPlayerMetaData.active_seconds * 1000 : null
                        }
                        timestampFormat={timestampFormat}
                        startTime={sessionPlayerData.start}
                    />
                </div>
            </div>
        </div>
    )
}
