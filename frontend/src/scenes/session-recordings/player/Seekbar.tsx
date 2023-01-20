import './Seekbar.scss'
import { useEffect, useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { seekbarLogic } from 'scenes/session-recordings/player/seekbarLogic'
import { RecordingSegment } from '~/types'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from './sessionRecordingPlayerLogic'
import { Timestamp } from './PlayerControllerTime'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { autoCaptureEventToDescription, capitalizeFirstLetter, colonDelimitedDuration } from 'lib/utils'
import { playerInspectorLogic } from './inspector/playerInspectorLogic'

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

function PlayerSeekbarTicks(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { seekbarItems } = useValues(playerInspectorLogic(props))
    const { endTimeMs } = useValues(seekbarLogic(props))
    const { seekToTime } = useActions(sessionRecordingPlayerLogic(props))

    return (
        <div className="PlayerSeekbar__ticks">
            {seekbarItems.map((item, i) => (
                <div
                    key={i}
                    className={clsx(
                        'PlayerSeekbarTick',
                        item.highlightColor && `PlayerSeekbarTick--${item.highlightColor}`
                    )}
                    title={item.data.event}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: `${(item.timeInRecording / endTimeMs) * 100}%`,
                        zIndex: i + (item.highlightColor ? 1000 : 0),
                    }}
                    onClick={(e) => {
                        e.stopPropagation()
                        seekToTime(item.timeInRecording)
                    }}
                >
                    <div className="PlayerSeekbarTick__info">
                        <PropertyKeyInfo
                            className="font-medium"
                            disableIcon
                            disablePopover
                            ellipsis={true}
                            value={capitalizeFirstLetter(autoCaptureEventToDescription(item.data))}
                        />
                        {item.data.event === '$autocapture' ? (
                            <span className="opacity-75 ml-2">(Autocapture)</span>
                        ) : null}
                        {item.data.event === '$pageview' ? (
                            <span className="ml-2 opacity-75">
                                {item.data.properties.$pathname || item.data.properties.$current_url}
                            </span>
                        ) : null}
                    </div>
                    <div className="PlayerSeekbarTick__line" />
                </div>
            ))}
        </div>
    )
}

export function Seekbar(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const sliderRef = useRef<HTMLDivElement | null>(null)
    const thumbRef = useRef<HTMLDivElement | null>(null)
    const { handleDown, setSlider, setThumb } = useActions(seekbarLogic(props))
    const { sessionPlayerData } = useValues(sessionRecordingDataLogic(props))
    const { thumbLeftPos, bufferPercent, isScrubbing } = useValues(seekbarLogic(props))

    // Workaround: Something with component and logic mount timing that causes slider and thumb
    // reducers to be undefined.
    useEffect(() => {
        if (sliderRef.current && thumbRef.current) {
            setSlider(sliderRef)
            setThumb(thumbRef)
        }
    }, [sliderRef.current, thumbRef.current, props.sessionRecordingId])

    return (
        <div className="flex items-center h-8" data-attr="rrweb-controller">
            <Timestamp {...props} />
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
                                // eslint-disable-next-line react/forbid-dom-props
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

                <PlayerSeekbarTicks {...props} />
            </div>
        </div>
    )
}
