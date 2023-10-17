import './Seekbar.scss'
import { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import clsx from 'clsx'
import { seekbarLogic } from './seekbarLogic'
import { RecordingSegment } from '~/types'
import { sessionRecordingDataLogic } from '../sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { Timestamp } from './PlayerControllerTime'
import { playerInspectorLogic } from '../inspector/playerInspectorLogic'
import { PlayerSeekbarPreview } from './PlayerSeekbarPreview'
import { PlayerSeekbarTicks } from './PlayerSeekbarTicks'

export function Seekbar(): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)
    const { seekbarItems } = useValues(playerInspectorLogic(logicProps))
    const { endTimeMs, thumbLeftPos, bufferPercent, isScrubbing } = useValues(seekbarLogic(logicProps))

    const { handleDown, setSlider, setThumb } = useActions(seekbarLogic(logicProps))
    const { sessionPlayerData } = useValues(sessionRecordingDataLogic(logicProps))

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
        <div className="flex items-end h-8 mx-2 mt-2" data-attr="rrweb-controller">
            <Timestamp />
            <div className="flex flex-col w-full">
                <PlayerSeekbarTicks seekbarItems={seekbarItems} endTimeMs={endTimeMs} seekToTime={seekToTime} />

                <div className={clsx('PlayerSeekbar', { 'PlayerSeekbar--scrubbing': isScrubbing })} ref={seekBarRef}>
                    <div
                        className="PlayerSeekbar__slider"
                        ref={sliderRef}
                        onMouseDown={handleDown}
                        onTouchStart={handleDown}
                    >
                        <div className="PlayerSeekbar__segments">
                            {sessionPlayerData.segments?.map((segment: RecordingSegment) => (
                                <div
                                    key={`${segment.startTimestamp}-${segment.endTimestamp}`}
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
                        <div
                            className="PlayerSeekbar__currentbar"
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

                        <PlayerSeekbarPreview minMs={0} maxMs={sessionPlayerData.durationMs} seekBarRef={seekBarRef} />
                    </div>
                </div>
            </div>
        </div>
    )
}
