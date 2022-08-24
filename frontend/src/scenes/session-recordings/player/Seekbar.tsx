import './Seekbar.scss'
import React, { useEffect, useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { seekbarLogic } from 'scenes/session-recordings/player/seekbarLogic'
import { RecordingEventType, RecordingSegment } from '~/types'
import { sessionRecordingLogic } from '../sessionRecordingLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

function Tick({ event }: { event: RecordingEventType }): JSX.Element {
    const [hovering, setHovering] = useState(false)
    const { handleTickClick } = useActions(seekbarLogic)
    const { reportRecordingPlayerSeekbarEventHovered } = useActions(eventUsageLogic)
    return (
        <div
            className="tick-hover-box"
            style={{
                left: `calc(${event.percentageOfRecordingDuration}% - 2px)`,
            }}
            onClick={(e) => {
                e.stopPropagation()
                event.playerPosition && handleTickClick(event.playerPosition)
            }}
            onMouseEnter={(e) => {
                e.stopPropagation()
                setHovering(true)
                reportRecordingPlayerSeekbarEventHovered()
            }}
            onMouseLeave={(e) => {
                e.stopPropagation()
                setHovering(false)
            }}
        >
            <div className={clsx('tick-info', { show: hovering })}>{event.event}</div>
            <div className="tick-marker" />
            <div className={clsx('tick-thumb', { big: hovering })} />
        </div>
    )
}

export function Seekbar(): JSX.Element {
    const sliderRef = useRef<HTMLDivElement | null>(null)
    const thumbRef = useRef<HTMLDivElement | null>(null)
    const { handleDown, setSlider, setThumb } = useActions(seekbarLogic)
    const { eventsToShow, sessionPlayerData } = useValues(sessionRecordingLogic)
    const { thumbLeftPos, bufferPercent } = useValues(seekbarLogic)

    // Workaround: Something with component and logic mount timing that causes slider and thumb
    // reducers to be undefined.
    useEffect(() => {
        if (sliderRef.current && thumbRef.current) {
            setSlider(sliderRef)
            setThumb(thumbRef)
        }
    }, [sliderRef.current, thumbRef.current])

    return (
        <div className="rrweb-controller-slider">
            <div className="slider" ref={sliderRef} onMouseDown={handleDown} onTouchStart={handleDown}>
                <div className="inactivity-bar">
                    {sessionPlayerData?.metadata?.segments?.map((segment: RecordingSegment) => (
                        <div
                            key={`${segment.windowId}-${segment.startTimeEpochMs}`}
                            className={clsx('activity-section', !segment.isActive && 'inactive-section')}
                            style={{
                                width: `${
                                    (100 * segment.durationMs) / sessionPlayerData.metadata.recordingDurationMs
                                }%`,
                            }}
                        />
                    ))}
                </div>
                <div className="slider-bar" />
                <div className="thumb" ref={thumbRef} style={{ transform: `translateX(${thumbLeftPos}px)` }} />
                <div className="current-bar" style={{ width: `${Math.max(thumbLeftPos, 0)}px` }} />
                <div className="buffer-bar" style={{ width: `calc(${bufferPercent}% - 2px)` }} />
            </div>
            <div className="ticks">
                {eventsToShow.map((event: RecordingEventType) => (
                    <Tick key={event.id} event={event} />
                ))}
            </div>
        </div>
    )
}
