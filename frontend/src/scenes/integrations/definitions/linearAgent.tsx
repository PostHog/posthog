import { ICONS } from 'lib/integrations/utils'

import { LinearAgentIntegration } from '../components/Integrations'
import { defineIntegration } from '../integrationDefinition'

export const LinearAgent = defineIntegration(
    {
        slug: 'linear-agent',
        kind: 'linear-agent',
        name: 'Linear (Agent)',
        logo: ICONS['linear-agent'],
        subtitle: 'Let PostHog Code pick up Linear issues and open PRs',
        description:
            'Assign a Linear issue to PostHog Code (or @-mention it) and it creates a coding task, opens a PR, and comments the link back on the issue.',
        capabilities: [
            'Create a PostHog Code task when an issue is assigned to the agent',
            'Open a pull request for the change',
            'Comment the PR link back on the Linear issue',
        ],
        docsUrl: 'https://posthog.com/docs/integrate',
    },
    LinearAgentIntegration
)
