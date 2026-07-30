import { WizardDestination, WizardTrigger } from 'lib/components/Alerting/AlertWizard/alertWizardLogic'

import { HogFunctionSubTemplateIdType } from '~/types'

export const HEALTH_ALERT_SUB_TEMPLATE_IDS: HogFunctionSubTemplateIdType[] = [
    'health-check-firing',
    'health-check-resolved',
]

export const HEALTH_ALERT_TRIGGERS: WizardTrigger[] = [
    {
        key: 'health-check-firing',
        name: 'Health check fired',
        description: 'Get notified when a health issue is newly detected',
    },
    {
        key: 'health-check-resolved',
        name: 'Health check resolved',
        description: 'Get notified when a previously active health issue clears',
    },
]

// Note: `template-email` is intentionally not offered here. It's a hidden template
// meant only for use inside workflows, not as a standalone destination — the backend
// rejects it on create, so selecting it in the wizard would 400 on save.
export const HEALTH_ALERT_DESTINATIONS: WizardDestination[] = [
    {
        key: 'slack',
        name: 'Slack',
        description: 'Send a message to a channel',
        icon: '/static/services/slack.png',
        templateId: 'template-slack',
    },
    {
        key: 'discord',
        name: 'Discord',
        description: 'Post a notification via webhook',
        icon: '/static/services/discord.png',
        templateId: 'template-discord',
    },
    {
        key: 'microsoft-teams',
        name: 'Teams',
        description: 'Send a message to a channel',
        icon: '/static/services/microsoft-teams.png',
        templateId: 'template-microsoft-teams',
    },
    {
        key: 'webhook',
        name: 'Webhook',
        description: 'Send an HTTP request to any URL',
        icon: '/static/services/webhook.svg',
        templateId: 'template-webhook',
    },
]
