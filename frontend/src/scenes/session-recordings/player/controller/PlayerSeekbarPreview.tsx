import { colonDelimitedDuration } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
import { PlayerFrame } from '../PlayerFrame'
import { BindLogic, useActions, useValues } from 'kea'
import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { useDebouncedCallback } from 'use-debounce'

export type PlayerSeekbarPreviewProps = {
    minMs: number
    maxMs: number
}

const PlayerSeekbarPreviewFrame = ({
    percentage,
    minMs,
    maxMs,
}: { percentage: number } & PlayerSeekbarPreviewProps): JSX.Element => {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)

    const seekPlayerLogicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId: sessionRecordingId,
        playerKey: `${logicProps.playerKey}-preview`,
        autoPlay: false,
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
        debouncedSeekToTime(minMs + (maxMs - minMs) * percentage)
    }, [percentage, minMs, maxMs])

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={seekPlayerLogicProps}>
            <div className="bg-red w-60 h-40">
                <PlayerFrame />
            </div>
        </BindLogic>
    )
}

export function PlayerSeekbarPreview({ minMs, maxMs }: PlayerSeekbarPreviewProps): JSX.Element {
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
        <div className="PlayerSeekBarPreview" ref={ref}>
            <div
                className="PlayerSeekBarPreview__tooltip"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    transform: `translateX(${percentage * 100}%)`,
                }}
            >
                <div className="PlayerSeekBarPreview__tooltip__content">
                    <FlaggedFeature flag={FEATURE_FLAGS.SESSION_RECORDING_PLAYER_PREVIEW} match>
                        <PlayerSeekbarPreviewFrame minMs={minMs} maxMs={maxMs} percentage={percentage} />
                    </FlaggedFeature>
                    <div className="text-center p-2">{content}</div>
                </div>
            </div>
        </div>
    )
}
