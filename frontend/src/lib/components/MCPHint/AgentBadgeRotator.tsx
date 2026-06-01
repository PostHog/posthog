import { useState } from 'react'

import { useInterval } from 'lib/hooks/useInterval'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

// Show PostHog Code more often to increase engagement
const AGENTS = ['PostHog Code', 'Claude', 'Cursor', 'PostHog Code', 'Codex', 'Gemini'] as const

const ROTATE_INTERVAL_MS = 3000
const POSTHOG_CODE_URL = 'https://posthog.com/code'

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
    const agent = AGENTS[safeIndex]
    const classes = cn('font-semibold rainbow-text-fading', {
        'rainbow-text-animating': !isStorybook,
    })

    return (
        <span className={cn('inline-flex relative', className)} aria-live="polite">
            {agent === 'PostHog Code' ? (
                /* oxlint-disable-next-line forbid-elements */
                <a href={POSTHOG_CODE_URL} target="_blank" rel="noopener noreferrer" key={agent} className={classes}>
                    {agent}
                </a>
            ) : (
                <span key={agent} className={classes}>
                    {agent}
                </span>
            )}
        </span>
    )
}
