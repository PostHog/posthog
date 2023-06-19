import './Seekbar.scss'
import { memo, useEffect, useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { seekbarLogic } from 'scenes/session-recordings/player/seekbarLogic'
import { RecordingSegment } from '~/types'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { Timestamp } from './PlayerControllerTime'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { autoCaptureEventToDescription, capitalizeFirstLetter, colonDelimitedDuration } from 'lib/utils'
import { InspectorListItemEvent, playerInspectorLogic } from './inspector/playerInspectorLogic'

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

function PlayerSeekbarTick(props: {
    item: InspectorListItemEvent
    endTimeMs: number
    zIndex: number
    onClick: (e: React.MouseEvent) => void
}): JSX.Element {
    return (
        <div
            className={clsx(
                'PlayerSeekbarTick',
                props.item.highlightColor && `PlayerSeekbarTick--${props.item.highlightColor}`
            )}
            title={props.item.data.event}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: `${(props.item.timeInRecording / props.endTimeMs) * 100}%`,
                zIndex: props.zIndex,
            }}
            onClick={props.onClick}
        >
            <div className="PlayerSeekbarTick__info">
                <PropertyKeyInfo
                    className="font-medium"
                    disableIcon
                    disablePopover
                    ellipsis={true}
                    value={capitalizeFirstLetter(autoCaptureEventToDescription(props.item.data))}
                />
                {props.item.data.event === '$autocapture' ? (
                    <span className="opacity-75 ml-2">(Autocapture)</span>
                ) : null}
                {props.item.data.event === '$pageview' ? (
                    <span className="ml-2 opacity-75">
                        {props.item.data.properties.$pathname || props.item.data.properties.$current_url}
                    </span>
                ) : null}
            </div>
            <div className="PlayerSeekbarTick__line" />
        </div>
    )
}

const PlayerSeekbarTicks = memo(
    function PlayerSeekbarTicks({
        seekbarItems,
        endTimeMs,
        seekToTime,
    }: {
        seekbarItems: InspectorListItemEvent[]
        endTimeMs: number
        seekToTime: (timeInMilliseconds: number) => void
    }): JSX.Element {
        return (
            <div className="PlayerSeekbar__ticks">
                {seekbarItems.map((item, i) => {
                    return (
                        <PlayerSeekbarTick
                            key={item.data.id}
                            item={item}
                            endTimeMs={endTimeMs}
                            zIndex={i + (item.highlightColor ? 1000 : 0)}
                            onClick={(e) => {
                                e.stopPropagation()
                                seekToTime(item.timeInRecording)
                            }}
                        />
                    )
                })}
            </div>
        )
    },
    (prev, next) => {
        const seekbarItemsAreEqual =
            prev.seekbarItems.length === next.seekbarItems.length &&
            prev.seekbarItems.every((item, i) => item.data.id === next.seekbarItems[i].data.id)

        return seekbarItemsAreEqual && prev.endTimeMs === next.endTimeMs && prev.seekToTime === next.seekToTime
    }
)

export function Seekbar(): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)
    const { seekbarItems } = useValues(playerInspectorLogic(logicProps))
    const { endTimeMs, thumbLeftPos, bufferPercent, isScrubbing } = useValues(seekbarLogic(logicProps))

    const { handleDown, setSlider, setThumb } = useActions(seekbarLogic(logicProps))
    const { sessionPlayerData } = useValues(sessionRecordingDataLogic(logicProps))

    const sliderRef = useRef<HTMLDivElement | null>(null)
    const thumbRef = useRef<HTMLDivElement | null>(null)

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
            <Timestamp />
            <div className={clsx('PlayerSeekbar', { 'PlayerSeekbar--scrubbing': isScrubbing })}>
                <div
                    className="PlayerSeekbar__slider"
                    ref={sliderRef}
                    onMouseDown={handleDown}
                    onTouchStart={handleDown}
                >
                    <div className="PlayerSeekbar__segments">
                        {sessionPlayerData.segments?.map((segment: RecordingSegment) => (
                            <div
                                key={`${segment.windowId}-${segment.startTimestamp}`}
                                className={clsx(
                                    'PlayerSeekbar__segments__item',
                                    segment.isActive && 'PlayerSeekbar__segments__item--active'
                                )}
                                title={!segment.isActive ? 'Inactive period' : 'Active period'}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    width: `${(100 * segment.durationMs) / sessionPlayerData.durationMs}%`,
                                }}
                            />
                        ))}
                    </div>

                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <div className="PlayerSeekbar__currentbar" style={{ width: `${Math.max(thumbLeftPos, 0)}px` }} />
                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <div className="PlayerSeekbar__bufferbar" style={{ width: `${bufferPercent}%` }} />
                    <div
                        className="PlayerSeekbar__thumb"
                        ref={thumbRef}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ transform: `translateX(${thumbLeftPos}px)` }}
                    />

                    <PlayerSeekbarInspector minMs={0} maxMs={sessionPlayerData.durationMs} />
                </div>

                <PlayerSeekbarTicks seekbarItems={seekbarItems} endTimeMs={endTimeMs} seekToTime={seekToTime} />
            </div>
        </div>
    )
}
