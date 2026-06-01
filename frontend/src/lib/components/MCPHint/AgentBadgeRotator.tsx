import { useMemo, useState } from 'react'

import { useInterval } from 'lib/hooks/useInterval'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { getAgentRotation } from './agentWeights'
import type { SurfaceKey } from './prompts'

const ROTATE_INTERVAL_MS = 2000

export function AgentBadgeRotator({
    className,
    surfaceKey,
}: {
    className?: string
    /**
     * When provided, biases the rotation toward agents the audience for this surface
     * tends to use (e.g. IDE agents for SQL/flags, chat agents for dashboards).
     */
    surfaceKey?: SurfaceKey
}): JSX.Element {
    // Pin to "PostHog Code" inside Storybook so visual snapshots don't flake on rotation.
    const isStorybook = inStorybook() || inStorybookTestRunner()

    const agents = useMemo(() => getAgentRotation(surfaceKey), [surfaceKey])
    const [index, setIndex] = useState(() => (isStorybook ? 0 : Math.floor(Math.random() * agents.length)))

    useInterval(() => {
        if (isStorybook) {
            return
        }

        setIndex((current) => (current + 1) % agents.length)
    }, ROTATE_INTERVAL_MS)

    const safeIndex = index % agents.length
    return (
        <span className={cn('inline-flex relative', className)} aria-live="polite">
            <span
                key={agents[safeIndex]}
                className={cn('font-semibold rainbow-text-fading', {
                    'rainbow-text-animating': !isStorybook,
                })}
            >
                {agents[safeIndex]}
            </span>
        </span>
    )
}
