import { WizardDestination, WizardTrigger } from 'scenes/hog-functions/AlertWizard/alertWizardLogic'

import { HogFunctionSubTemplateIdType } from '~/types'

export const SDK_DOCTOR_SUB_TEMPLATE_IDS: HogFunctionSubTemplateIdType[] = ['sdk-doctor-outdated-sdk']

export const SDK_DOCTOR_TRIGGERS: WizardTrigger[] = [
    {
        key: 'sdk-doctor-outdated-sdk',
        name: 'SDK is outdated',
        description: 'Get notified when your team has outdated PostHog SDKs',
    },
]

export const SDK_DOCTOR_DESTINATIONS: WizardDestination[] = [
    {
        key: 'email',
        name: 'Email',
        description: 'Send an email notification',
        icon: '/static/posthog-icon.svg',
        templateId: 'template-email',
    },
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
