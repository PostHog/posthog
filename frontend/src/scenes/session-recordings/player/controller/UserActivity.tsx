import useSize from '@react-hook/size'
import { useValues } from 'kea'
import { MutableRefObject, useMemo, useRef } from 'react'

import { cn } from 'lib/utils/css-classes'
import { playerUsesWatchLayout } from 'scenes/session-recordings/playlist/replayLayout'

import useIsHovering from '~/lib/hooks/useIsHovering'

import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { ActivityPoint, activityAreaPath } from './activityCurvePath'

export function UserActivity({ hoverRef }: { hoverRef: MutableRefObject<HTMLDivElement | null> }): JSX.Element {
    const { activityPerSecond, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { replayLayout } = useValues(playerSettingsLogic)
    // The watch layout keeps the curve on screen. The classic seekbar reveals it on hover.
    const watchLayout = playerUsesWatchLayout(replayLayout, logicProps)

    const seekBarRef = useRef<HTMLDivElement | null>(null)
    const [width, height] = useSize(seekBarRef)

    const isHovering = useIsHovering(hoverRef)

    const points: ActivityPoint[] = useMemo(() => {
        return Object.entries(activityPerSecond.smoothedPoints).map(([second, activity]) => ({
            x: (parseInt(second, 10) / activityPerSecond.durationSeconds) * width,
            y: height - (Math.log(activity.y + 1) / Math.log(activityPerSecond.maxY + 1)) * height,
        }))
    }, [activityPerSecond, width, height])

    const hasPoints = points.length > 0

    return (
        <div
            className={cn(
                'absolute bottom-0 w-full bg-gradient-to-t from-surface-primary via-surface-primary to-transparent from-0% via-96% to-100% transition-opacity duration-300',
                {
                    'opacity-0': !isHovering && !watchLayout,
                }
            )}
            ref={seekBarRef}
            // if there are no points, we don't want to take up space
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: hasPoints ? '3rem' : '0' }}
        >
            <svg width="100%" height="100%" preserveAspectRatio="none">
                <path
                    d={activityAreaPath(points, width, height, watchLayout)}
                    fill="var(--color-bg-fill-highlight-200)"
                    stroke="none"
                />
            </svg>
        </div>
    )
}
