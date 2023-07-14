import { colonDelimitedDuration, debounce } from 'lib/utils'
import { Ref, RefObject, useEffect, useMemo, useRef, useState } from 'react'
import { PlayerFrame } from '../PlayerFrame'
import { BindLogic, useActions, useValues } from 'kea'
import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export function PlayerSeekbarPreview({
    minMs,
    maxMs,
    parentRef,
}: {
    minMs: number
    maxMs: number
    parentRef: RefObject<HTMLDivElement>
}): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)

    const [percentage, setPercentage] = useState<number>(0)
    const ref = useRef<HTMLDivElement>(null)
    const fixedUnits = maxMs / 1000 > 3600 ? 3 : 2
    const content = colonDelimitedDuration(minMs / 1000 + ((maxMs - minMs) / 1000) * percentage, fixedUnits)

    const seekPlayerLogicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId: sessionRecordingId,
        playerKey: `${logicProps.playerKey}-preview`,
        autoPlay: false,
    }

    const { setPause, seekToTime } = useActions(sessionRecordingPlayerLogic(seekPlayerLogicProps))

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

    const debouncedSeekToTime = useMemo(
        () =>
            debounce((time: number) => {
                setPause()
                seekToTime(time)
            }, 100),
        [minMs, maxMs, seekToTime]
    )

    useEffect(() => {
        debouncedSeekToTime(minMs + (maxMs - minMs) * percentage)
    }, [content])

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
                    <BindLogic logic={sessionRecordingPlayerLogic} props={seekPlayerLogicProps}>
                        <div className="bg-red w-60 h-40">
                            <PlayerFrame />
                        </div>
                    </BindLogic>
                    <div className="text-center p-2">{content}</div>
                </div>
            </div>
        </div>
    )
}
