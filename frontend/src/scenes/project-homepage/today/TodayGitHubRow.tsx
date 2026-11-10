import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { Button, IconStack, IconStackItem } from '@posthog/quill'

import { todayGetStartedLogic } from './todayGetStartedLogic'

export function TodayGitHubRow({ fixCount }: { fixCount: number }): JSX.Element | null {
    const { githubConnected, integrationsLoading, githubDismissed, aiEnabled } = useValues(todayGetStartedLogic)
    const { stepActed } = useActions(todayGetStartedLogic)

    if (!aiEnabled || integrationsLoading || githubConnected || githubDismissed) {
        return null
    }
    return (
        <ol className="TodayRows">
            <li className="TodayRow TodayGitHubRow" data-attr="today-github-row">
                <IconStack className="TodayRow__icons">
                    <IconStackItem>
                        <IconGithub />
                    </IconStackItem>
                </IconStack>
                <div className="min-w-0">
                    <span className="TodayRow__title">Connect GitHub to get pull requests</span>
                    <p className="TodayRow__meta">
                        {fixCount === 1
                            ? '1 report below has a fix PostHog can open as a pull request.'
                            : `${fixCount} reports below have fixes PostHog can open as pull requests.`}
                    </p>
                </div>
                <div className="TodayRow__end TodayGitHubRow__actions">
                    <Button
                        size="sm"
                        variant="link-muted"
                        onClick={() => stepActed('github', 'skip')}
                        data-attr="today-github-row-dismiss"
                    >
                        Not now
                    </Button>
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={() => stepActed('github', 'connect')}
                        data-attr="today-github-row-connect"
                    >
                        <IconGithub />
                        Connect GitHub
                    </Button>
                </div>
            </li>
        </ol>
    )
}
