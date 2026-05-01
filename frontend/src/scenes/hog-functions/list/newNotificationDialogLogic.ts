import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { CyclotronJobFiltersType, HogFunctionSubTemplateIdType, HogFunctionType } from '~/types'

import { HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES, HOG_FUNCTION_SUB_TEMPLATES } from '../sub-templates/sub-templates'
import type { newNotificationDialogLogicType } from './newNotificationDialogLogicType'

export type DestinationKey = 'slack' | 'discord' | 'microsoft-teams' | 'webhook'

export const DESTINATION_OPTIONS: {
    value: DestinationKey
    label: string
    templateId: string
    iconUrl: string
}[] = [
    { value: 'slack', label: 'Slack', templateId: 'template-slack', iconUrl: '/static/services/slack.png' },
    { value: 'discord', label: 'Discord', templateId: 'template-discord', iconUrl: '/static/services/discord.png' },
    {
        value: 'microsoft-teams',
        label: 'Microsoft Teams',
        templateId: 'template-microsoft-teams',
        iconUrl: '/static/services/microsoft-teams.png',
    },
    { value: 'webhook', label: 'Webhook', templateId: 'template-webhook', iconUrl: '/static/services/webhook.svg' },
]

export interface NewNotificationForm {
    destination: DestinationKey
    slackIntegrationId: number | null
    slackChannel: string | null
    webhookUrl: string
}

export interface NewNotificationDialogLogicProps {
    subTemplateId: HogFunctionSubTemplateIdType
    onCreated: () => void
    filtersOverride?: CyclotronJobFiltersType
}

export const newNotificationDialogLogic = kea<newNotificationDialogLogicType>([
    path(['scenes', 'hog-functions', 'list', 'newNotificationDialogLogic']),
    props({} as NewNotificationDialogLogicProps),
    key((props) => `${props.subTemplateId}-${JSON.stringify(props.filtersOverride ?? null)}`),
    connect(() => ({
        values: [integrationsLogic, ['integrations']],
    })),

    actions({
        openDialog: true,
        closeDialog: true,
    }),

    reducers({
        isOpen: [
            false,
            {
                openDialog: () => true,
                closeDialog: () => false,
            },
        ],
    }),

    forms(({ props }) => ({
        notificationForm: {
            defaults: {
                destination: 'slack',
                slackIntegrationId: null,
                slackChannel: null,
                webhookUrl: '',
            } as NewNotificationForm,
            errors: ({ destination, slackIntegrationId, slackChannel, webhookUrl }) => ({
                slackIntegrationId:
                    destination === 'slack' && !slackIntegrationId ? 'Please select a Slack workspace' : undefined,
                slackChannel: destination === 'slack' && !slackChannel ? 'Please select a channel' : undefined,
                webhookUrl:
                    destination !== 'slack' &&
                    !(webhookUrl.trim() && URL.canParse(webhookUrl.trim()) && /^https?:\/\//.test(webhookUrl.trim()))
                        ? 'Please enter a webhook URL'
                        : undefined,
            }),
            submit: async ({ destination, slackIntegrationId, slackChannel, webhookUrl }) => {
                const destinationOption = DESTINATION_OPTIONS.find((d) => d.value === destination)
                if (!destinationOption) {
                    return
                }

                const template = await api.hogFunctions.getTemplate(destinationOption.templateId)
                const subTemplate = HOG_FUNCTION_SUB_TEMPLATES[props.subTemplateId].find(
                    (st) => st.template_id === destinationOption.templateId
                )
                const commonProps = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[props.subTemplateId]

                // Build inputs from template defaults
                const inputs: Record<string, { value: unknown }> = {}
                for (const schema of template.inputs_schema ?? []) {
                    if (schema.default !== undefined) {
                        inputs[schema.key] = { value: schema.default }
                    }
                }

                // Apply sub-template input overrides (custom message templates, etc.)
                if (subTemplate?.inputs) {
                    for (const [key, val] of Object.entries(subTemplate.inputs)) {
                        inputs[key] = val as { value: unknown }
                    }
                }

                // Apply destination-specific user inputs
                switch (destination) {
                    case 'slack':
                        inputs.slack_workspace = { value: slackIntegrationId }
                        inputs.channel = { value: slackChannel?.split('|')[0] }
                        break
                    case 'discord':
                        inputs.webhookUrl = { value: webhookUrl }
                        break
                    case 'microsoft-teams':
                        inputs.webhookUrl = { value: webhookUrl }
                        break
                    case 'webhook':
                        inputs.url = { value: webhookUrl }
                        break
                }

                const payload: Partial<HogFunctionType> = {
                    template_id: destinationOption.templateId,
                    type: commonProps.type,
                    name: subTemplate?.name ?? `Notify ${destinationOption.label}`,
                    description: subTemplate?.description ?? '',
                    inputs_schema: template.inputs_schema,
                    inputs,
                    filters: props.filtersOverride ?? commonProps.filters,
                    hog: template.code,
                    icon_url: template.icon_url,
                    enabled: true,
                }

                await api.hogFunctions.create(payload)
            },
        },
    })),

    selectors({
        selectedSlackIntegration: [
            (s) => [s.integrations, s.notificationForm],
            (integrations, form) => integrations?.find((i) => i.id === form.slackIntegrationId) ?? null,
        ],
    }),

    listeners(({ actions, props }) => ({
        submitNotificationFormSuccess: () => {
            lemonToast.success('Notification created successfully')
            actions.closeDialog()
            props.onCreated()
        },
        submitNotificationFormFailure: () => {
            lemonToast.error('Failed to create notification. Please try again.')
        },
        closeDialog: () => {
            actions.resetNotificationForm()
        },
    })),
])
