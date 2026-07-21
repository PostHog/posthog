import { useState } from 'react'

import { IconExternal, IconLogomark } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { useInterval } from 'lib/hooks/useInterval'
import { IconSlack } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import { AgentLogo, claudeLogo, cursorLogo, geminiLogo, openaiLogo } from '../AgentPromptButton/AgentLogo'

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
const POSTHOG_SLACK_URL = 'https://posthog.com/slack'
const POSTHOG_CODE_LOGO = <IconLogomark className="size-4 shrink-0 text-black dark:text-white" />
const POSTHOG_SLACK_LOGO = <IconSlack className="size-4 shrink-0" />

// Show PostHog Code + Slack more often to increase engagement
// Also duplicate the entries to keep it in the screen for longer
const AGENTS: BadgeAgent[] = [
    { name: 'PostHog Code', logo: POSTHOG_CODE_LOGO, url: POSTHOG_CODE_URL },
    { name: 'PostHog Code', logo: POSTHOG_CODE_LOGO, url: POSTHOG_CODE_URL },
    { name: 'Slack', logo: POSTHOG_SLACK_LOGO, url: POSTHOG_SLACK_URL },
    { name: 'Claude', logo: claudeLogo },
    { name: 'Cursor', logo: cursorLogo, logoClassName: 'dark:invert' },
    { name: 'PostHog Code', logo: POSTHOG_CODE_LOGO, url: POSTHOG_CODE_URL },
    { name: 'PostHog Code', logo: POSTHOG_CODE_LOGO, url: POSTHOG_CODE_URL },
    { name: 'Slack', logo: POSTHOG_SLACK_LOGO, url: POSTHOG_SLACK_URL },
    { name: 'Codex', logo: openaiLogo },
    { name: 'Gemini', logo: geminiLogo },
    { name: 'PostHog Code', logo: POSTHOG_CODE_LOGO, url: POSTHOG_CODE_URL },
    { name: 'PostHog Code', logo: POSTHOG_CODE_LOGO, url: POSTHOG_CODE_URL },
    { name: 'Slack', logo: POSTHOG_SLACK_LOGO, url: POSTHOG_SLACK_URL },
    { name: 'ChatGPT', logo: openaiLogo },
    { name: 'Claude Code', logo: claudeLogo },
]

const ROTATE_INTERVAL_MS = 3000

export function AgentBadgeRotator(): JSX.Element {
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

    const wrapperClassname = 'inline-flex items-center gap-1'
    const textClassname = cn('font-semibold rainbow-text-fading', {
        'rainbow-text-animating': !isStorybook,
    })

    return (
        <div className="inline-flex items-center relative align-text-bottom mb-[-2px]" aria-live="polite">
            {agent.url ? (
                <Link to={agent.url} target="_blank" className={wrapperClassname}>
                    <AgentLogo logo={agent.logo} logoClassName={agent.logoClassName} />
                    <span key={agent.name} className={textClassname}>
                        {agent.name}
                    </span>
                    <IconExternal className="size-3 text-muted" />
                </Link>
            ) : (
                <span className={wrapperClassname}>
                    <AgentLogo logo={agent.logo} logoClassName={agent.logoClassName} />
                    <span key={agent.name} className={textClassname}>
                        {agent.name}
                    </span>
                </span>
            )}
        </div>
    )
}
