import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayPromptRow } from './TodayPromptRow'
import { todayPromptsLogic } from './todayPromptsLogic'

export function TodayGitHubRow({ fixCount }: { fixCount: number }): JSX.Element | null {
    const { aiEnabled, githubConnected, integrationsLoading, githubDismissed } = useValues(todayPromptsLogic)
    const { dismissPrompt } = useActions(todayPromptsLogic)

    if (!aiEnabled || integrationsLoading || githubConnected || githubDismissed) {
        return null
    }
    return (
        <TodayPromptRow
            icon={{ glyph: <IconGithub /> }}
            title="Connect GitHub to get pull requests"
            meta={
                fixCount === 1
                    ? '1 report below has a fix PostHog can open as a pull request.'
                    : `${fixCount} reports below have fixes PostHog can open as pull requests.`
            }
            dataAttr="today-github-row"
            actions={
                <>
                    <Button
                        size="sm"
                        variant="link-muted"
                        onClick={() => dismissPrompt('github')}
                        data-attr="today-github-row-dismiss"
                    >
                        Not now
                    </Button>
                    <Button
                        size="sm"
                        variant="outline"
                        render={<LinkPrimitive to={urls.settings('project-integrations')} />}
                        data-attr="today-github-row-connect"
                    >
                        <IconGithub />
                        Connect GitHub
                    </Button>
                </>
            }
        />
    )
}
