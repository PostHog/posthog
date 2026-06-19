import { WizardDestination, WizardTrigger } from 'scenes/hog-functions/AlertWizard/alertWizardLogic'

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
        key: 'email',
        name: 'Email',
        description: 'Send an email notification',
        icon: '/static/posthog-icon.svg',
        templateId: 'template-email',
    },
    {
        key: 'webhook',
        name: 'Webhook',
        description: 'Send an HTTP request to any URL',
        icon: '/static/services/webhook.svg',
        templateId: 'template-webhook',
    },
]
