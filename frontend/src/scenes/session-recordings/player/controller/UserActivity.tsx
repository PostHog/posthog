import useSize from '@react-hook/size'
import { useValues } from 'kea'
import { cn } from 'lib/utils/css-classes'
import { MutableRefObject, useMemo, useRef } from 'react'

import useIsHovering from '~/lib/hooks/useIsHovering'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { seekbarLogic } from './seekbarLogic'

interface ActivityPoint {
    x: number
    y: number
}

export function UserActivity({ hoverRef }: { hoverRef: MutableRefObject<HTMLDivElement | null> }): JSX.Element {
    const { activityPerSecond, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { endTimeMs: durationMs } = useValues(seekbarLogic(logicProps))

    const seekBarRef = useRef<HTMLDivElement | null>(null)
    const [width, height] = useSize(seekBarRef)
    const durationInSeconds = durationMs / 1000

    const isHovering = useIsHovering(hoverRef)

    const points: ActivityPoint[] = useMemo(() => {
        const maxY = Math.max(...Object.values(activityPerSecond).map((activity) => activity.y))

        return Object.entries(activityPerSecond).map(([second, activity]) => ({
            x: (parseInt(second, 10) / durationInSeconds) * width,
            y: height - (Math.log(activity.y + 1) / Math.log(maxY + 1)) * height,
        }))
    }, [activityPerSecond, durationInSeconds, width, height])

    const hasPoints = points.length > 0

    return (
        <div
            className={cn(
                'absolute bottom-0 w-full bg-gradient-to-t from-surface-primary via-surface-primary to-transparent from-0% via-96% to-100% transition-opacity duration-300',
                {
                    'opacity-0': !isHovering,
                }
            )}
            ref={seekBarRef}
            // if there are no points, we don't want to take up space
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: hasPoints ? '3rem' : '0' }}
        >
            <svg width="100%" height="100%" preserveAspectRatio="none">
                <path
                    d={
                        points.length
                            ? `
                        M 0,${height}
                        ${points.map((point) => `L ${point.x},${point.y}`).join(' ')}
                        L ${width},${height}
                        Z
                    `
                            : ''
                    }
                    fill="var(--bg-fill-highlight-200)"
                    stroke="none"
                />
            </svg>
        </div>
    )
}
