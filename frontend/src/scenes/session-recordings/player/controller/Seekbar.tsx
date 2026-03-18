import './Seekbar.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'
import React from 'react'

import { SourceLoadingState } from '@posthog/replay-shared'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

import { playerInspectorLogic } from '../inspector/playerInspectorLogic'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingDataCoordinatorLogic } from '../sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSeekbarPreview } from './PlayerSeekbarPreview'
import { PlayerSeekbarTicks } from './PlayerSeekbarTicks'
import { seekbarLogic } from './seekbarLogic'

const SeekbarSources = React.memo(function SeekbarSourcesRaw({
    sourceLoadingStates,
    recordingStartMs,
    recordingEndMs,
}: {
    sourceLoadingStates: SourceLoadingState[]
    recordingStartMs: number
    recordingEndMs: number
}): JSX.Element | null {
    if (!sourceLoadingStates.length) {
        return null
    }

    const items: JSX.Element[] = []
    let cursor = recordingStartMs

    for (let i = 0; i < sourceLoadingStates.length; i++) {
        const s = sourceLoadingStates[i]
        const loaded = s.state === 'loaded'
        // Gap before this source — inherits this source's state
        if (s.startMs > cursor) {
            items.push(
                <div
                    key={`gap-${i}`}
                    className={cn('PlayerSeekbar__sources__item', loaded && 'PlayerSeekbar__sources__item--loaded')}
                    style={{ flex: `${s.startMs - cursor} 0 0px` }} // eslint-disable-line react/forbid-dom-props
                />
            )
        }
        items.push(
            <div
                key={i}
                className={cn('PlayerSeekbar__sources__item', loaded && 'PlayerSeekbar__sources__item--loaded')}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ flex: `${s.endMs - s.startMs} 0 0px` }}
            />
        )
        cursor = s.endMs
    }

    // Gap after last source — inherits last source's state
    if (cursor < recordingEndMs) {
        const lastLoaded = sourceLoadingStates[sourceLoadingStates.length - 1].state === 'loaded'
        items.push(
            <div
                key="gap-end"
                className={cn('PlayerSeekbar__sources__item', lastLoaded && 'PlayerSeekbar__sources__item--loaded')}
                style={{ flex: `${recordingEndMs - cursor} 0 0px` }} // eslint-disable-line react/forbid-dom-props
            />
        )
    }

    return <div className="PlayerSeekbar__sources">{items}</div>
})

export function Seekbar(): JSX.Element {
    const { sessionRecordingId, logicProps, hasSnapshots } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)
    const { seekbarItems } = useValues(playerInspectorLogic(logicProps))
    const { endTimeMs, thumbLeftPos, isScrubbing } = useValues(seekbarLogic(logicProps))
    const { timestampFormat } = useValues(playerSettingsLogic)

    const { handleDown, setSlider, setThumb } = useActions(seekbarLogic(logicProps))
    const { sessionPlayerData, sessionPlayerMetaData, effectiveSourceLoadingStates } = useValues(
        sessionRecordingDataCoordinatorLogic(logicProps)
    )

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
        <div className="flex flex-col items-end mx-4 mt-2 h-8" data-attr="rrweb-controller">
            <PlayerSeekbarTicks
                seekbarItems={seekbarItems}
                endTimeMs={endTimeMs}
                seekToTime={seekToTime}
                hoverRef={seekBarRef}
            />

            <div
                className={cn('PlayerSeekbar', {
                    'PlayerSeekbar--scrubbing': isScrubbing,
                })}
                ref={seekBarRef}
            >
                <div
                    className="PlayerSeekbar__slider ph-no-rageclick"
                    ref={sliderRef}
                    onMouseDown={handleDown}
                    onTouchStart={handleDown}
                >
                    <SeekbarSources
                        sourceLoadingStates={effectiveSourceLoadingStates}
                        recordingStartMs={sessionPlayerData.start?.valueOf() ?? 0}
                        recordingEndMs={sessionPlayerData.end?.valueOf() ?? 0}
                    />
                    <div
                        className="PlayerSeekbar__played"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${Math.max(thumbLeftPos, 0)}px` }}
                    />

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
