import { WizardDestination, WizardTrigger } from 'lib/components/Alerting/AlertWizard/alertWizardLogic'

import { HogFunctionSubTemplateIdType } from '~/types'

export const SOURCE_ALERT_SUB_TEMPLATE_IDS: HogFunctionSubTemplateIdType[] = [
    'data-warehouse-sync-failed',
    'data-warehouse-sync-recovered',
    'data-warehouse-sync-completed',
    'data-warehouse-billing-limit-reached',
]

export const SOURCE_ALERT_TRIGGERS: WizardTrigger[] = [
    {
        key: 'data-warehouse-sync-failed',
        name: 'Sync failed',
        description: 'Get notified when a sync fails',
    },
    {
        key: 'data-warehouse-sync-recovered',
        name: 'Sync recovered',
        description: 'Get notified when a sync works again after it failed',
    },
    {
        key: 'data-warehouse-sync-completed',
        name: 'Sync completed',
        description: 'Get notified when a sync finishes',
    },
    {
        key: 'data-warehouse-billing-limit-reached',
        name: 'Billing limit reached',
        description: 'Get notified when a sync stops because of your billing limit',
    },
]

export const SOURCE_ALERT_DESTINATIONS: WizardDestination[] = [
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
