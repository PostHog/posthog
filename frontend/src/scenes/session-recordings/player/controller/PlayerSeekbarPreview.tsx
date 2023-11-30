import { BindLogic, useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import useIsHovering from 'lib/hooks/useIsHovering'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { colonDelimitedDuration } from 'lib/utils'
import { MutableRefObject, useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { PlayerFrame } from '../PlayerFrame'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
    SessionRecordingPlayerMode,
} from '../sessionRecordingPlayerLogic'

const TWENTY_MINUTES_IN_MS = 20 * 60 * 1000

export type PlayerSeekbarPreviewProps = {
    minMs: number
    maxMs: number
    seekBarRef: MutableRefObject<HTMLDivElement | null>
    activeMs: number | null
}

const PlayerSeekbarPreviewFrame = ({
    percentage,
    minMs,
    maxMs,
    isVisible,
}: { percentage: number; isVisible: boolean } & Omit<
    PlayerSeekbarPreviewProps,
    'seekBarRef' | 'activeMs'
>): JSX.Element => {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)

    const seekPlayerLogicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId: sessionRecordingId,
        playerKey: `${logicProps.playerKey}-preview`,
        autoPlay: false,
        mode: SessionRecordingPlayerMode.Preview,
    }

    const { setPause, seekToTime } = useActions(sessionRecordingPlayerLogic(seekPlayerLogicProps))

    const debouncedSeekToTime = useDebouncedCallback(
        (time: number) => {
            setPause()
            seekToTime(time)
        },
        200,
        {
            maxWait: 500,
        }
    )

    useEffect(() => {
        if (isVisible) {
            debouncedSeekToTime(minMs + (maxMs - minMs) * percentage)
        }
    }, [percentage, minMs, maxMs, isVisible])

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={seekPlayerLogicProps}>
            <div className="bg-red w-60 h-40">
                <PlayerFrame />
            </div>
        </BindLogic>
    )
}

export function PlayerSeekbarPreview({ minMs, maxMs, seekBarRef, activeMs }: PlayerSeekbarPreviewProps): JSX.Element {
    const [percentage, setPercentage] = useState<number>(0)
    const ref = useRef<HTMLDivElement>(null)
    const fixedUnits = maxMs / 1000 > 3600 ? 3 : 2
    const content = colonDelimitedDuration(minMs / 1000 + ((maxMs - minMs) / 1000) * percentage, fixedUnits)

    const isHovering = useIsHovering(seekBarRef)

    const { featureFlags } = useValues(featureFlagLogic)
    const alwaysShowSeekbarPreview = !!featureFlags[FEATURE_FLAGS.ALWAYS_SHOW_SEEKBAR_PREVIEW]
    const canShowPreview = alwaysShowSeekbarPreview || (typeof activeMs === 'number' && activeMs < TWENTY_MINUTES_IN_MS)

    useEffect(() => {
        if (!seekBarRef?.current) {
            return
        }

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

        seekBarRef.current.addEventListener('mousemove', handleMouseMove)
        // fixes react-hooks/exhaustive-deps warning about stale ref elements
        const { current } = ref
        return () => current?.removeEventListener('mousemove', handleMouseMove)
    }, [seekBarRef])

    return (
        <div className="PlayerSeekBarPreview" ref={ref}>
            <div
                className="PlayerSeekBarPreview__tooltip"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    transform: `translateX(${percentage * 100}%)`,
                }}
            >
                <div className="PlayerSeekBarPreview__tooltip__content">
                    {canShowPreview && (
                        <PlayerSeekbarPreviewFrame
                            minMs={minMs}
                            maxMs={maxMs}
                            percentage={percentage}
                            isVisible={isHovering}
                        />
                    )}
                    <div className="text-center p-2">{content}</div>
                </div>
            </div>
        </div>
    )
}
