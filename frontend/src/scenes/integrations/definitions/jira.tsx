import { ICONS } from 'lib/integrations/utils'

import { JiraIntegration } from '../components/Integrations'
import { defineIntegration } from '../integrationDefinition'

export const Jira = defineIntegration(
    {
        slug: 'jira',
        kind: 'jira',
        name: 'Jira',
        logo: ICONS.jira,
        subtitle: 'Create and link Jira issues from PostHog',
        description: 'Connect Jira to create and link issues directly from PostHog error tracking and replays.',
        capabilities: [
            'Create Jira issues from error tracking',
            'Link existing Jira issues to PostHog',
            'Keep your team in sync across tools',
        ],
        docsUrl: 'https://posthog.com/docs/error-tracking/integrations',
    },
    JiraIntegration
)
