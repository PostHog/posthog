import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function OtherAgentSettings(): JSX.Element {
    return (
        <ul className="flex flex-col gap-2 max-w-200 list-disc pl-5 mb-0">
            <li>
                Self-driving agents, scouts, and signal sources are in{' '}
                <Link to={urls.inbox('settings')}>Inbox settings</Link>.
            </li>
            <li>
                Skills have their own page: <Link to={urls.skills()}>Skills</Link>.
            </li>
            <li>
                Workspaces, worktrees, local environments, the terminal, harness permission rules, keep awake, Discord,
                and app updates stay in PostHog Desktop, because they need your computer.
            </li>
        </ul>
    )
}
