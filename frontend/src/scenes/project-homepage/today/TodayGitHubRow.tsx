import { useActions, useValues } from 'kea'

import { IconGithub, IconHide } from '@posthog/icons'
import { Button, IconStack, IconStackItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { todayGetStartedLogic } from './todayGetStartedLogic'

export function TodayGitHubRow({ fixCount }: { fixCount: number }): JSX.Element | null {
    const { githubConnected, integrationsLoading, githubRowHidden } = useValues(todayGetStartedLogic)
    const { stepActed, hideGitHubRow } = useActions(todayGetStartedLogic)

    if (integrationsLoading || githubConnected || githubRowHidden) {
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
                <div className="TodayRow__end">
                    <div className="TodayRow__actions">
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Button
                                        variant="link-muted"
                                        size="icon-sm"
                                        aria-label="Hide"
                                        onClick={hideGitHubRow}
                                        data-attr="today-github-row-hide"
                                    />
                                }
                            >
                                <IconHide className="size-3.5" />
                            </TooltipTrigger>
                            <TooltipContent side="bottom">Hide</TooltipContent>
                        </Tooltip>
                    </div>
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
