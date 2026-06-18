import { ICONS } from 'lib/integrations/utils'

import { SlackIntegration } from '../components/SlackIntegration'
import { defineIntegration } from '../integrationDefinition'

export const Slack = defineIntegration(
    {
        slug: 'slack',
        kind: 'slack',
        name: 'Slack',
        logo: ICONS.slack,
        banner: 'https://res.cloudinary.com/dmukukwp6/image/upload/slack_app_update_docs_f0c917f70a',
        subtitle: 'Bring PostHog into Slack — from scheduled reports to an AI agent that ships code',
        description:
            'Tag @PostHog in any Slack thread to draft pull requests, ship code changes, ask data questions, and run SQL — all without leaving Slack. You also get insights, dashboards, and alerts delivered straight to your channels.',
        capabilities: [
            'Tag @PostHog in a thread to draft pull requests and ship code changes',
            'Tag @PostHog to ask data questions and run SQL',
            'Subscribe to insights and dashboards for scheduled reports',
            'Receive alerts and error-tracking notifications in your channels',
            'Manage feature flags, experiments, and surveys from Slack',
        ],
        docsUrl: 'https://posthog.com/docs/webhooks/slack',
    },
    SlackIntegration
)
