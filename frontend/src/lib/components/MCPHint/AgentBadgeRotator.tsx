import { useState } from 'react'

import { IconLogomark } from '@posthog/icons'

import { useInterval } from 'lib/hooks/useInterval'
import { IconSlack } from 'lib/lemon-ui/icons'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { AgentLogo, claudeLogo, cursorLogo, geminiLogo, openaiLogo } from '../AgentPromptButton/agentLogos'

interface BadgeAgent {
    name: string
    /** Brand SVG URL (string from an SVG import) or an inline icon element */
    logo: string | React.ReactElement
    /** Extra classes for SVG logos (e.g. `dark:invert` for monochrome marks) */
    logoClassName?: string
    /** When set, the badge renders as a link to this URL */
    url?: string
}

const POSTHOG_CODE_URL = 'https://posthog.com/code'

// Show PostHog Code more often to increase engagement
const AGENTS: BadgeAgent[] = [
    { name: 'PostHog Code', logo: <IconLogomark className="size-4 shrink-0" />, url: POSTHOG_CODE_URL },
    { name: 'Claude', logo: claudeLogo },
    { name: 'Cursor', logo: cursorLogo, logoClassName: 'dark:invert' },
    { name: 'PostHog Code', logo: <IconLogomark className="size-4 shrink-0" />, url: POSTHOG_CODE_URL },
    { name: 'Codex', logo: openaiLogo },
    { name: 'Gemini', logo: geminiLogo },
    { name: 'Slack', logo: <IconSlack className="size-4 shrink-0" />, url: 'https://posthog.com/slack' },
]

const ROTATE_INTERVAL_MS = 3000

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

    const agent = AGENTS[index]
    const nameClasses = cn('font-semibold rainbow-text-fading', {
        'rainbow-text-animating': !isStorybook,
    })

    return (
        <span className={cn('inline-flex items-center gap-1 relative', className)} aria-live="polite">
            <AgentLogo logo={agent.logo} logoClassName={agent.logoClassName} />
            {agent.url ? (
                /* oxlint-disable-next-line forbid-elements */
                <a href={agent.url} target="_blank" rel="noopener noreferrer" key={agent.name} className={nameClasses}>
                    {agent.name}
                </a>
            ) : (
                <span key={agent.name} className={nameClasses}>
                    {agent.name}
                </span>
            )}
        </span>
    )
}
