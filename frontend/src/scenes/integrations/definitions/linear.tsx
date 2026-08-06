import { ICONS } from 'lib/integrations/utils'

import { LinearIntegration } from '../components/Integrations'
import { defineIntegration } from '../integrationDefinition'

export const Linear = defineIntegration(
    {
        slug: 'linear',
        kind: 'linear',
        name: 'Linear',
        logo: ICONS.linear,
        subtitle: 'Turn issues into Linear tickets without leaving PostHog',
        description: 'Connect Linear to create and link issues directly from PostHog error tracking and replays.',
        capabilities: [
            'Create Linear issues from error tracking',
            'Link existing Linear issues to PostHog',
            'Keep engineering work connected to product signals',
        ],
        docsUrl: 'https://posthog.com/docs/error-tracking/integrations',
    },
    LinearIntegration
)
