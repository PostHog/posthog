import './Seekbar.scss'
import { useEffect, useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { seekbarLogic } from 'scenes/session-recordings/player/seekbarLogic'
import { RecordingEventType, RecordingSegment } from '~/types'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { eventsListLogic } from 'scenes/session-recordings/player/inspector/eventsListLogic'
import { RowStatus } from 'scenes/session-recordings/player/inspector/listLogic'
import { SessionRecordingPlayerLogicProps } from './sessionRecordingPlayerLogic'
import { Timestamp } from './PlayerControllerTime'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { autoCaptureEventToDescription, capitalizeFirstLetter, colonDelimitedDuration } from 'lib/utils'

interface TickProps extends SessionRecordingPlayerLogicProps {
    event: RecordingEventType
    index: number
    status: RowStatus
    numEvents: number
}

function PlayerSeekbarInspector({ minMs, maxMs }: { minMs: number; maxMs: number }): JSX.Element {
    const [percentage, setPercentage] = useState<number>(0)
    const ref = useRef<HTMLDivElement>(null)
    const fixedUnits = maxMs / 1000 > 3600 ? 3 : 2
    const content = colonDelimitedDuration(minMs / 1000 + ((maxMs - minMs) / 1000) * percentage, fixedUnits)

    useEffect(() => {
        const handleMouseMove = (e: MouseEvent): void => {
            const rect = ref.current?.getBoundingClientRect()

            if (!rect) {
                return
            }
            const relativeX = e.clientX - rect.x
            const newPercentage = Math.max(Math.min(relativeX / rect.width, 1), 0)

            if (newPercentage !== percentage) {
                setPercentage(newPercentage)
            }
        }

        window.addEventListener('mousemove', handleMouseMove)
        return () => window.removeEventListener('mousemove', handleMouseMove)
    }, [])

    return (
        <div className="PlayerSeekBarInspector" ref={ref}>
            <div
                className="PlayerSeekBarInspector__tooltip"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    transform: `translateX(${percentage * 100}%)`,
                }}
            >
                <div className="PlayerSeekBarInspector__tooltip__content">{content}</div>
            </div>
        </div>
    )
}

function PlayerSeekbarTick({ event, sessionRecordingId, playerKey, status, numEvents, index }: TickProps): JSX.Element {
    const { handleTickClick } = useActions(seekbarLogic({ sessionRecordingId, playerKey }))
    const { reportRecordingPlayerSeekbarEventHovered } = useActions(eventUsageLogic)
    const zIndexOffset = !!status ? numEvents : 0 // Bump up the important events

    const hoverTimeoutRef = useRef<any>(null)

    useEffect(() => {
        return () => {
            clearTimeout(hoverTimeoutRef.current)
        }
    }, [])

    return (
        <div
            className={clsx('PlayerSeekbarTick', status === RowStatus.Match && 'PlayerSeekbarTick--match')}
            title={event.event}
            style={{
                left: `${event.percentageOfRecordingDuration}%`,
                zIndex: zIndexOffset + index,
            }}
            onClick={(e) => {
                e.stopPropagation()
                event.playerPosition && handleTickClick(event.playerPosition)
            }}
            onMouseEnter={() => {
                // We only want to report the event hover if the user is hovering over the tick for more than 1 second
                hoverTimeoutRef.current = setTimeout(() => {
                    reportRecordingPlayerSeekbarEventHovered()
                }, 500)
            }}
            onMouseLeave={() => {
                clearTimeout(hoverTimeoutRef.current)
            }}
        >
            <div className="PlayerSeekbarTick__info">
                <PropertyKeyInfo
                    className="font-medium"
                    disableIcon
                    disablePopover
                    ellipsis={true}
                    value={capitalizeFirstLetter(autoCaptureEventToDescription(event))}
                />
                {event.event === '$autocapture' ? <span className="opacity-75 ml-2">(Autocapture)</span> : null}
                {event.event === '$pageview' ? (
                    <span className="ml-2 opacity-75">
                        {event.properties.$pathname || event.properties.$current_url}
                    </span>
                ) : null}
            </div>
            <div className="PlayerSeekbarTick__line" />
        </div>
    )
}

export function Seekbar({ sessionRecordingId, playerKey }: SessionRecordingPlayerLogicProps): JSX.Element {
    const sliderRef = useRef<HTMLDivElement | null>(null)
    const thumbRef = useRef<HTMLDivElement | null>(null)
    const { handleDown, setSlider, setThumb } = useActions(seekbarLogic({ sessionRecordingId, playerKey }))
    const { sessionPlayerData } = useValues(sessionRecordingDataLogic({ sessionRecordingId }))
    const { eventListData } = useValues(eventsListLogic({ sessionRecordingId, playerKey }))
    const { thumbLeftPos, bufferPercent, isScrubbing } = useValues(seekbarLogic({ sessionRecordingId, playerKey }))

    // Workaround: Something with component and logic mount timing that causes slider and thumb
    // reducers to be undefined.
    useEffect(() => {
        if (sliderRef.current && thumbRef.current) {
            setSlider(sliderRef)
            setThumb(thumbRef)
        }
    }, [sliderRef.current, thumbRef.current, sessionRecordingId])

    return (
        <div className="flex items-center h-8" data-attr="rrweb-controller">
            <Timestamp sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            <div className={clsx('PlayerSeekbar', { 'PlayerSeekbar--scrubbing': isScrubbing })}>
                <div
                    className="PlayerSeekbar__slider"
                    ref={sliderRef}
                    onMouseDown={handleDown}
                    onTouchStart={handleDown}
                >
                    <div className="PlayerSeekbar__segments">
                        {sessionPlayerData?.metadata?.segments?.map((segment: RecordingSegment) => (
                            <div
                                key={`${segment.windowId}-${segment.startTimeEpochMs}`}
                                className={clsx(
                                    'PlayerSeekbar__segments__item',
                                    segment.isActive && 'PlayerSeekbar__segments__item--active'
                                )}
                                title={!segment.isActive ? 'Inactive period' : 'Active period'}
                                style={{
                                    width: `${
                                        (100 * segment.durationMs) / sessionPlayerData.metadata.recordingDurationMs
                                    }%`,
                                }}
                            />
                        ))}
                    </div>

                    <div className="PlayerSeekbar__currentbar" style={{ width: `${Math.max(thumbLeftPos, 0)}px` }} />
                    <div className="PlayerSeekbar__bufferbar" style={{ width: `${bufferPercent}%` }} />
                    <div
                        className="PlayerSeekbar__thumb"
                        ref={thumbRef}
                        style={{ transform: `translateX(${thumbLeftPos}px)` }}
                    />

                    <PlayerSeekbarInspector minMs={0} maxMs={sessionPlayerData.metadata.recordingDurationMs} />
                </div>
                <div className="PlayerSeekbar__ticks">
                    {eventListData.map((event: RecordingEventType, i) => (
                        <PlayerSeekbarTick
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
        </div>
    )
}
