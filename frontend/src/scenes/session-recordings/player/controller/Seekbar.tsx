import './Seekbar.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'
import React from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

import { RecordingSegment } from '~/types'

import { playerInspectorLogic } from '../inspector/playerInspectorLogic'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingDataCoordinatorLogic } from '../sessionRecordingDataCoordinatorLogic'
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
            className={cn(
                'PlayerSeekbar__segments__item',
                segment.isActive && 'PlayerSeekbar__segments__item--active',
                segment.kind === 'buffer' && 'PlayerSeekbar__segments__item--buffer',
                segment.isLoading && 'PlayerSeekbar__segments__item--buffer-loading'
            )}
            title={segment.kind === 'buffer' ? undefined : segment.isActive ? 'Active period' : 'Inactive period'}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: `${(100 * segment.durationMs) / durationMs}%`,
            }}
        />
    )
})

function SeekbarSegments(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { segments, durationMs } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))
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

export function Seekbar(): JSX.Element {
    const { sessionRecordingId, logicProps, hasSnapshots } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)
    const { seekbarItems } = useValues(playerInspectorLogic(logicProps))
    const { endTimeMs, thumbLeftPos, bufferPercent, isScrubbing } = useValues(seekbarLogic(logicProps))
    const { timestampFormat } = useValues(playerSettingsLogic)

    const { handleDown, setSlider, setThumb } = useActions(seekbarLogic(logicProps))
    const { sessionPlayerData, sessionPlayerMetaData } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))

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
    }, [sliderRef.current, thumbRef.current, sessionRecordingId]) // oxlint-disable-line react-hooks/exhaustive-deps

    const allowPreviewScrubbing = useFeatureFlag('SEEKBAR_PREVIEW_SCRUBBING')

    return (
        <div className="flex flex-col items-end h-8 mx-4 mt-2" data-attr="rrweb-controller">
            <PlayerSeekbarTicks
                seekbarItems={seekbarItems}
                endTimeMs={endTimeMs}
                seekToTime={seekToTime}
                hoverRef={seekBarRef}
            />

            <div className={cn('PlayerSeekbar', { 'PlayerSeekbar--scrubbing': isScrubbing })} ref={seekBarRef}>
                <div
                    className="PlayerSeekbar__slider ph-no-rageclick"
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

                    {hasSnapshots && allowPreviewScrubbing ? (
                        <PlayerSeekbarPreview
                            minMs={0}
                            maxMs={sessionPlayerData.durationMs}
                            seekBarRef={seekBarRef}
                            activeMs={
                                sessionPlayerMetaData?.active_seconds
                                    ? sessionPlayerMetaData.active_seconds * 1000
                                    : null
                            }
                            timestampFormat={timestampFormat}
                            startTime={sessionPlayerData.start}
                        />
                    ) : null}
                </div>
            </div>
        </div>
    )
}
