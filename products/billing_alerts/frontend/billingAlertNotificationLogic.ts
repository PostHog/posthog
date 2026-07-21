import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { IntegrationType, OrganizationType } from '~/types'

import { billingAlertsLogic } from './billingAlertsLogic'
import { billingAlertRequestError, destinationKey } from './billingAlertUtils'
import { billingAlertsDestinationsDeleteCreate } from './generated/api'
import type {
    BillingAlertConfigurationApi,
    BillingAlertDestinationCreateDataApi,
    BillingAlertDestinationSummaryApi,
} from './generated/api.schemas'

export type BillingAlertNotificationType = 'slack' | 'teams' | 'webhook'

export interface PendingBillingAlertDestination {
    key: string
    label: string
    payload: BillingAlertDestinationCreateDataApi
}

export interface BillingAlertNotificationLogicProps {
    alert: BillingAlertConfigurationApi | null
}

export function isHttpsUrl(value: string): boolean {
    const trimmed = value.trim()
    if (!trimmed) {
        return false
    }
    try {
        return new URL(trimmed).protocol === 'https:'
    } catch {
        return false
    }
}

export interface billingAlertNotificationLogicValues {
    currentOrganization: OrganizationType | null
    currentTeamId: number | null
    integrations: IntegrationType[] | null
    slackIntegrations: IntegrationType[]
    selectedSlackIntegration: IntegrationType | undefined
    pendingDestinations: PendingBillingAlertDestination[]
    selectedType: BillingAlertNotificationType
    selectedIntegrationId: number | null
    slackChannel: string | null
    webhookUrl: string
    addDisabledReason: string | undefined
    executionTeamMismatch: boolean
    deletingDestinationKeys: Set<string>
}

export interface billingAlertNotificationLogicActions {
    setSelectedType: (selectedType: BillingAlertNotificationType) => { selectedType: BillingAlertNotificationType }
    setSelectedIntegrationId: (integrationId: number | null) => { integrationId: number | null }
    setSlackChannel: (slackChannel: string | null) => { slackChannel: string | null }
    setWebhookUrl: (webhookUrl: string) => { webhookUrl: string }
    addSelectedDestination: () => { value: true }
    addPendingDestination: (destination: PendingBillingAlertDestination) => {
        destination: PendingBillingAlertDestination
    }
    removePendingDestination: (key: string) => { key: string }
    clearCreatedDestinations: (keys: string[]) => { keys: string[] }
    setDestinationDeleting: (key: string, deleting: boolean) => { key: string; deleting: boolean }
    deleteDestination: (destination: BillingAlertDestinationSummaryApi) => {
        destination: BillingAlertDestinationSummaryApi
    }
    loadAlerts: () => void
    alertUpdated: (alert: BillingAlertConfigurationApi) => { alert: BillingAlertConfigurationApi }
}

export type billingAlertNotificationLogicType = MakeLogicType<
    billingAlertNotificationLogicValues,
    billingAlertNotificationLogicActions,
    BillingAlertNotificationLogicProps
>

export const billingAlertNotificationLogic = kea<billingAlertNotificationLogicType>([
    path(['products', 'billingAlerts', 'frontend', 'billingAlertNotificationLogic']),
    props({} as BillingAlertNotificationLogicProps),
    key(({ alert }) => alert?.id ?? 'new'),
    connect({
        values: [
            billingLogic,
            ['currentOrganization'],
            teamLogic,
            ['currentTeamId'],
            integrationsLogic,
            ['integrations'],
        ],
        actions: [billingAlertsLogic, ['loadAlerts', 'alertUpdated']],
    }),
    actions({
        setSelectedType: (selectedType: BillingAlertNotificationType) => ({ selectedType }),
        setSelectedIntegrationId: (integrationId: number | null) => ({ integrationId }),
        setSlackChannel: (slackChannel: string | null) => ({ slackChannel }),
        setWebhookUrl: (webhookUrl: string) => ({ webhookUrl }),
        addSelectedDestination: true,
        addPendingDestination: (destination: PendingBillingAlertDestination) => ({ destination }),
        removePendingDestination: (key: string) => ({ key }),
        clearCreatedDestinations: (keys: string[]) => ({ keys }),
        deleteDestination: (destination: BillingAlertDestinationSummaryApi) => ({ destination }),
        setDestinationDeleting: (key: string, deleting: boolean) => ({ key, deleting }),
    }),
    reducers({
        pendingDestinations: [
            [] as PendingBillingAlertDestination[],
            {
                addPendingDestination: (state, { destination }) => [...state, destination],
                removePendingDestination: (state, { key }) => state.filter((destination) => destination.key !== key),
                clearCreatedDestinations: (state, { keys }) =>
                    state.filter((destination) => !keys.includes(destination.key)),
            },
        ],
        selectedType: [
            'slack' as BillingAlertNotificationType,
            { setSelectedType: (_, { selectedType }) => selectedType },
        ],
        // null means "no explicit choice": selectedSlackIntegration falls back to the first workspace.
        selectedIntegrationId: [
            null as number | null,
            {
                setSelectedIntegrationId: (_, { integrationId }) => integrationId,
            },
        ],
        slackChannel: [
            null as string | null,
            {
                setSlackChannel: (_, { slackChannel }) => slackChannel,
                setSelectedIntegrationId: () => null,
            },
        ],
        webhookUrl: [
            '',
            {
                setWebhookUrl: (_, { webhookUrl }) => webhookUrl,
            },
        ],
        deletingDestinationKeys: [
            new Set<string>(),
            {
                setDestinationDeleting: (state, { key, deleting }) =>
                    deleting ? new Set([...state, key]) : new Set([...state].filter((candidate) => candidate !== key)),
            },
        ],
    }),
    selectors({
        slackIntegrations: [
            (selectors) => [selectors.integrations],
            (integrations: IntegrationType[] | null): IntegrationType[] =>
                integrations?.filter((integration) => integration.kind === 'slack') ?? [],
        ],
        selectedSlackIntegration: [
            (selectors) => [selectors.slackIntegrations, selectors.selectedIntegrationId],
            (integrations: IntegrationType[], integrationId: number | null): IntegrationType | undefined =>
                integrations.find((integration) => integration.id === integrationId) ?? integrations[0],
        ],
        executionTeamMismatch: [
            (selectors) => [(_, props) => props.alert, selectors.currentTeamId],
            (alert: BillingAlertConfigurationApi | null, currentTeamId: number | null): boolean =>
                Boolean(alert && currentTeamId && alert.execution_team_id !== currentTeamId),
        ],
        addDisabledReason: [
            (selectors) => [
                selectors.selectedType,
                selectors.selectedSlackIntegration,
                selectors.slackChannel,
                selectors.webhookUrl,
                selectors.pendingDestinations,
                (_, props) => props.alert,
                selectors.executionTeamMismatch,
            ],
            (
                selectedType: BillingAlertNotificationType,
                integration: IntegrationType | undefined,
                slackChannel: string | null,
                webhookUrl: string,
                pending: PendingBillingAlertDestination[],
                alert: BillingAlertConfigurationApi | null,
                executionTeamMismatch: boolean
            ): string | undefined => {
                if (alert?.destinations.some((destination) => destination.type === selectedType)) {
                    return 'This alert already has that destination type.'
                }
                if (pending.some((destination) => destination.payload.type === selectedType)) {
                    return 'That destination is already pending.'
                }
                if (selectedType === 'slack') {
                    if (executionTeamMismatch) {
                        return "Switch to this alert's execution project to use its Slack integrations."
                    }
                    if (!integration) {
                        return 'Connect Slack first.'
                    }
                    return slackChannel ? undefined : 'Select a Slack channel.'
                }
                return isHttpsUrl(webhookUrl) ? undefined : 'Enter a valid HTTPS webhook URL.'
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        addSelectedDestination: () => {
            if (values.addDisabledReason) {
                return
            }
            let pending: PendingBillingAlertDestination
            if (values.selectedType === 'slack' && values.selectedSlackIntegration && values.slackChannel) {
                const [channelId, channelLabel] = values.slackChannel.split('|')
                pending = {
                    key: `slack-${values.selectedSlackIntegration.id}-${channelId}`,
                    label: `Slack: ${channelLabel || channelId}`,
                    payload: {
                        type: 'slack',
                        slack_workspace_id: values.selectedSlackIntegration.id,
                        slack_channel_id: channelId,
                        slack_channel_name: channelLabel?.replace(/^#/, '') || channelId,
                    },
                }
                actions.setSlackChannel(null)
            } else {
                const url = values.webhookUrl.trim()
                pending = {
                    key: `${values.selectedType}-${url}`,
                    label: `${values.selectedType === 'teams' ? 'Microsoft Teams' : 'Webhook'}: ${url}`,
                    payload: { type: values.selectedType, webhook_url: url },
                }
                actions.setWebhookUrl('')
            }
            actions.addPendingDestination(pending)
        },
        deleteDestination: async ({ destination }) => {
            if (!values.currentOrganization?.id || !props.alert) {
                return
            }
            const key = destinationKey(destination)
            if (values.deletingDestinationKeys.has(key)) {
                return
            }
            actions.setDestinationDeleting(key, true)
            try {
                await billingAlertsDestinationsDeleteCreate(values.currentOrganization.id, props.alert.id, {
                    hog_function_ids: [...destination.hog_function_ids],
                })
                lemonToast.success('Destination removed.')
                const destinations = props.alert.destinations.filter((candidate) => destinationKey(candidate) !== key)
                actions.alertUpdated({
                    ...props.alert,
                    destinations,
                })
                actions.loadAlerts()
            } catch (error) {
                lemonToast.error(billingAlertRequestError(error))
            } finally {
                actions.setDestinationDeleting(key, false)
            }
        },
    })),
])
