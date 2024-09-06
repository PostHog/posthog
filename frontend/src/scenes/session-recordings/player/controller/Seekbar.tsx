import './Seekbar.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { RecordingSegment } from '~/types'

import { playerInspectorLogic } from '../inspector/playerInspectorLogic'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingDataLogic } from '../sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSeekbarPreview } from './PlayerSeekbarPreview'
import { PlayerSeekbarTicks } from './PlayerSeekbarTicks'
import { seekbarLogic } from './seekbarLogic'

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
