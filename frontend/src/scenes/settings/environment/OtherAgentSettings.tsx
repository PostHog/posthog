import { Link } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export function OtherAgentSettings(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <ul className="m-0 flex flex-col gap-2 max-w-200 list-disc pl-5">
                <Text size="xs" render={<li />}>
                    Self-driving agents, scouts, and signal sources are in{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.inbox('settings')} />}
                    >
                        Inbox settings
                    </Button>
                    .
                </Text>
                <Text size="xs" render={<li />}>
                    Skills have their own page:{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.skills()} />}
                    >
                        Skills
                    </Button>
                    .
                </Text>
                <Text size="xs" render={<li />}>
                    Workspaces, worktrees, local environments, the terminal, harness permission rules, keep awake,
                    Discord, and app updates stay in PostHog Desktop, because they need your computer.
                </Text>
            </ul>
        )
    }

    return (
        <ul className="flex flex-col gap-2 max-w-200 list-disc pl-5 mb-0">
            <li>
                Self-driving autonomy, steering, and notifications have their own section:{' '}
                <Link to={urls.settings('environment-self-driving')}>Self-driving</Link>. Scouts and signal sources are
                in the <Link to={urls.inbox('scouts')}>Self-driving inbox</Link>.
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
