import { Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ICONS } from 'lib/integrations/utils'
import { urls } from 'scenes/urls'

import { GithubIntegration } from '../components/Integrations'
import { defineIntegration } from '../integrationDefinition'

function GitHubDescription(): JSX.Element {
    const showDesktopEntryPoints = useFeatureFlag('POSTHOG_DESKTOP_ENTRY_POINTS')
    return (
        <>
            Connect GitHub to link issues and pull requests with PostHog and create issues directly from error tracking.
            With <Link to={urls.integration('slack')}>Slack</Link> and{' '}
            {showDesktopEntryPoints ? (
                <Link to="https://posthog.com/desktop" target="_blank">
                    PostHog Desktop
                </Link>
            ) : (
                <Link to={urls.taskTracker()}>PostHog tasks</Link>
            )}{' '}
            connected, tag @PostHog to draft pull requests and ship code changes straight to your repositories.
        </>
    )
}

export const GitHub = defineIntegration(
    {
        slug: 'github',
        kind: 'github',
        name: 'GitHub',
        logo: ICONS.github,
        subtitle: 'Link code, track issues, and let PostHog ship pull requests',
        description: <GitHubDescription />,
        capabilities: [
            'Let @PostHog draft pull requests and ship code changes',
            'Create GitHub issues from error tracking',
            'Link pull requests and issues to PostHog',
            'Attribute code changes across your repositories',
        ],
        docsUrl: 'https://posthog.com/docs/libraries/github',
    },
    GithubIntegration
)
