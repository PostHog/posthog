import { Link } from '@posthog/lemon-ui'

import { ICONS } from 'lib/integrations/utils'
import { urls } from 'scenes/urls'

import { GithubIntegration } from '../components/Integrations'
import { defineIntegration } from '../integrationDefinition'

export const GitHub = defineIntegration(
    {
        slug: 'github',
        kind: 'github',
        name: 'GitHub',
        logo: ICONS.github,
        subtitle: 'Link code, track issues, and let PostHog ship pull requests',
        description: (
            <>
                Connect GitHub to link issues and pull requests with PostHog and create issues directly from error
                tracking. With <Link to={urls.integration('slack')}>Slack</Link> and{' '}
                <Link to="https://posthog.com/code" target="_blank">
                    PostHog code
                </Link>{' '}
                connected, tag @PostHog to draft pull requests and ship code changes straight to your repositories.
            </>
        ),
        capabilities: [
            'Let @PostHog draft pull requests and ship code changes',
            'Create GitHub issues from error tracking',
            'Link pull requests and issues to PostHog',
            'Attribute code changes across your repositories',
        ],
        docsUrl: 'https://posthog.com/docs/error-tracking/integrations',
    },
    GithubIntegration
)
