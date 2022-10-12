import './Seekbar.scss'
import React, { useEffect, useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { seekbarLogic } from 'scenes/session-recordings/player/seekbarLogic'
import { RecordingEventType, RecordingSegment, SessionRecordingPlayerProps } from '~/types'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { eventsListLogic } from 'scenes/session-recordings/player/list/eventsListLogic'
import { RowStatus } from 'scenes/session-recordings/player/list/listLogic'

interface TickProps extends SessionRecordingPlayerProps {
    event: RecordingEventType
    index: number
    status: RowStatus
    numEvents: number
}

function Tick({ event, sessionRecordingId, playerKey, status, numEvents, index }: TickProps): JSX.Element {
    const [hovering, setHovering] = useState(false)
    const { handleTickClick } = useActions(seekbarLogic({ sessionRecordingId, playerKey }))
    const { reportRecordingPlayerSeekbarEventHovered } = useActions(eventUsageLogic)
    const zIndexOffset = !!status ? numEvents : 0 // Bump up the important events
    return (
        <div
            className="tick-hover-box"
            style={{
                left: `calc(${event.percentageOfRecordingDuration}% - 2px)`,
                zIndex: zIndexOffset + index,
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
            <div className={clsx('tick-info', { flex: hovering })}>{event.event}</div>
            <div className={clsx('tick-marker', status === RowStatus.Match ? 'bg-purple-dark' : 'bg-muted-alt')} />
            <div
                className={clsx(
                    'tick-thumb',
                    {
                        'tick-thumb__big': hovering,
                    },
                    status === RowStatus.Match ? 'border-light bg-purple-dark' : 'border-muted-alt bg-white'
                )}
            />
        </div>
    )
}

export function Seekbar({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const sliderRef = useRef<HTMLDivElement | null>(null)
    const thumbRef = useRef<HTMLDivElement | null>(null)
    const { handleDown, setSlider, setThumb } = useActions(seekbarLogic({ sessionRecordingId, playerKey }))
    const { sessionPlayerData } = useValues(sessionRecordingDataLogic({ sessionRecordingId }))
    const { eventListData } = useValues(eventsListLogic({ sessionRecordingId, playerKey }))
    const { thumbLeftPos, bufferPercent } = useValues(seekbarLogic({ sessionRecordingId, playerKey }))

    // Workaround: Something with component and logic mount timing that causes slider and thumb
    // reducers to be undefined.
    useEffect(() => {
        if (sliderRef.current && thumbRef.current) {
            setSlider(sliderRef)
            setThumb(thumbRef)
        }
    }, [sliderRef.current, thumbRef.current, sessionRecordingId])

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
                {eventListData.map((event: RecordingEventType, i) => (
                    <Tick
                        key={event.id}
                        index={i}
                        event={event}
                        sessionRecordingId={sessionRecordingId}
                        playerKey={playerKey}
                        status={event.level as RowStatus}
                        numEvents={eventListData.length}
                    />
                ))}
            </div>
        </div>
    )
}
