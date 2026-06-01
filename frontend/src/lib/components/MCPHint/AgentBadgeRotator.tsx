import { useState } from 'react'

import { useInterval } from 'lib/hooks/useInterval'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

// Show PostHog Code more often to increase engagement
const AGENTS = ['PostHog Code', 'Claude', 'Cursor', 'PostHog Code', 'Codex', 'Gemini'] as const

const ROTATE_INTERVAL_MS = 2000

export function AgentBadgeRotator({ className }: { className?: string }): JSX.Element {
    // Pin to "PostHog Code" inside Storybook so visual snapshots don't flake on rotation.
    const isStorybook = inStorybook() || inStorybookTestRunner()

    const [index, setIndex] = useState(() => (isStorybook ? 0 : Math.floor(Math.random() * AGENTS.length)))

    useInterval(() => {
        if (isStorybook) {
            return
        }

        setIndex((current) => (current + 1) % AGENTS.length)
    }, ROTATE_INTERVAL_MS)

    const safeIndex = index % AGENTS.length
    return (
        <span className={cn('inline-flex relative', className)} aria-live="polite">
            <span
                key={AGENTS[safeIndex]}
                className={cn('font-semibold rainbow-text-fading', {
                    'rainbow-text-animating': !isStorybook,
                })}
            >
                {AGENTS[safeIndex]}
            </span>
        </span>
    )
}
