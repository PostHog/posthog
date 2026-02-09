import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { IntegrationType, SlackChannelType, UserBasicType } from '~/types'

// Note: IntegrationType and SlackChannelType kept for legacy integration-based flow

import type { supportSettingsLogicType } from './supportSettingsLogicType'

export const supportSettingsLogic = kea<supportSettingsLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'settings', 'supportSettingsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam'],
            integrationsLogic,
            ['slackIntegrations', 'slackAvailable', 'integrations'],
        ],
        actions: [teamLogic, ['updateCurrentTeam', 'updateCurrentTeamSuccess']],
    })),
    actions({
        generateNewToken: true,
        setConversationsEnabledLoading: (loading: boolean) => ({ loading }),
        setWidgetEnabledLoading: (loading: boolean) => ({ loading }),
        // Domain management actions
        setIsAddingDomain: (isAdding: boolean) => ({ isAdding }),
        setEditingDomainIndex: (index: number | null) => ({ index }),
        setDomainInputValue: (value: string) => ({ value }),
        saveDomain: (value: string, editingIndex: number | null) => ({ value, editingIndex }),
        removeDomain: (index: number) => ({ index }),
        startEditDomain: (index: number) => ({ index }),
        cancelDomainEdit: true,
        setGreetingInputValue: (value: string | null) => ({ value }),
        saveGreetingText: true,
        // Identification form settings
        setIdentificationFormTitleValue: (value: string | null) => ({ value }),
        saveIdentificationFormTitle: true,
        setIdentificationFormDescriptionValue: (value: string | null) => ({ value }),
        saveIdentificationFormDescription: true,
        setPlaceholderTextValue: (value: string | null) => ({ value }),
        savePlaceholderText: true,
        // Notification recipients
        setNotificationRecipients: (users: UserBasicType[]) => ({ users }),
        // Slack channel settings (SupportHog)
        setSlackBotTokenValue: (value: string | null) => ({ value }),
        saveSlackBotToken: true,
        setSlackChannel: (channelId: string | null, channelName: string | null) => ({ channelId, channelName }),
        loadSlackChannelsWithToken: true,
        setSlackTicketEmojiValue: (value: string | null) => ({ value }),
        saveSlackTicketEmoji: true,
        disconnectSlack: true,
        // Legacy integration-based settings (kept for compatibility)
        setSlackIntegration: (integration: IntegrationType | null) => ({ integration }),
        loadSlackChannels: (integrationId: number) => ({ integrationId }),
    }),
    reducers({
        conversationsEnabledLoading: [
            false,
            {
                setConversationsEnabledLoading: (_, { loading }) => loading,
                updateCurrentTeamSuccess: () => false,
            },
        ],
        widgetEnabledLoading: [
            false,
            {
                setWidgetEnabledLoading: (_, { loading }) => loading,
                updateCurrentTeamSuccess: () => false,
            },
        ],
        isAddingDomain: [
            false,
            {
                setIsAddingDomain: (_, { isAdding }) => isAdding,
                saveDomain: () => false,
                cancelDomainEdit: () => false,
                startEditDomain: () => false,
            },
        ],
        editingDomainIndex: [
            null as number | null,
            {
                setEditingDomainIndex: (_, { index }) => index,
                saveDomain: () => null,
                cancelDomainEdit: () => null,
                setIsAddingDomain: () => null,
            },
        ],
        domainInputValue: [
            '',
            {
                setDomainInputValue: (_, { value }) => value,
                saveDomain: () => '',
                cancelDomainEdit: () => '',
                setIsAddingDomain: () => '',
            },
        ],
        greetingInputValue: [
            null as string | null,
            {
                setGreetingInputValue: (_, { value }) => value,
            },
        ],
        identificationFormTitleValue: [
            null as string | null,
            {
                setIdentificationFormTitleValue: (_, { value }) => value,
            },
        ],
        identificationFormDescriptionValue: [
            null as string | null,
            {
                setIdentificationFormDescriptionValue: (_, { value }) => value,
            },
        ],
        placeholderTextValue: [
            null as string | null,
            {
                setPlaceholderTextValue: (_, { value }) => value,
            },
        ],
        slackTicketEmojiValue: [
            null as string | null,
            {
                setSlackTicketEmojiValue: (_, { value }) => value,
            },
        ],
        slackBotTokenValue: [
            null as string | null,
            {
                setSlackBotTokenValue: (_, { value }) => value,
            },
        ],
    }),
    loaders(({ values }) => ({
        slackChannels: [
            [] as SlackChannelType[],
            {
                loadSlackChannels: async ({ integrationId }) => {
                    try {
                        const response = await api.integrations.slackChannels(integrationId, false)
                        return response.channels
                    } catch {
                        lemonToast.error('Failed to load Slack channels')
                        return values.slackChannels
                    }
                },
                loadSlackChannelsWithToken: async () => {
                    const token = values.slackBotToken
                    if (!token) {
                        return []
                    }
                    try {
                        const response = await api.create(`api/conversations/v1/slack/channels`, {
                            bot_token: token,
                        })
                        return response.channels || []
                    } catch {
                        lemonToast.error('Failed to load Slack channels')
                        return values.slackChannels
                    }
                },
            },
        ],
    })),
    selectors({
        conversationsDomains: [
            (s) => [s.currentTeam],
            (currentTeam): string[] => currentTeam?.conversations_settings?.widget_domains || [],
        ],
        notificationRecipients: [
            (s) => [s.currentTeam],
            (currentTeam): number[] => currentTeam?.conversations_settings?.notification_recipients || [],
        ],
        selectedSlackIntegration: [
            (s) => [s.currentTeam, s.slackIntegrations],
            (currentTeam, slackIntegrations): IntegrationType | null => {
                const integrationId = currentTeam?.conversations_settings?.slack_integration_id
                if (!integrationId || !slackIntegrations) {
                    return null
                }
                return slackIntegrations.find((i) => i.id === integrationId) ?? null
            },
        ],
        slackChannelId: [
            (s) => [s.currentTeam],
            (currentTeam): string | null => currentTeam?.conversations_settings?.slack_channel_id ?? null,
        ],
        slackChannelName: [
            (s) => [s.currentTeam],
            (currentTeam): string | null => currentTeam?.conversations_settings?.slack_channel_name ?? null,
        ],
        slackTicketEmoji: [
            (s) => [s.currentTeam],
            (currentTeam): string => currentTeam?.conversations_settings?.slack_ticket_emoji ?? 'ticket',
        ],
        slackBotToken: [
            (s) => [s.currentTeam],
            (currentTeam): string | null => currentTeam?.conversations_settings?.slack_bot_token ?? null,
        ],
        slackNeedsReauth: [
            (s) => [s.selectedSlackIntegration],
            (selectedIntegration): boolean => {
                if (!selectedIntegration) {
                    return false
                }
                const grantedScopes: string = selectedIntegration.config?.scope || ''
                const requiredScopes = ['channels:history', 'reactions:read', 'users:read']
                return requiredScopes.some((scope) => !grantedScopes.includes(scope))
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        generateNewToken: async () => {
            const response = await api.projects.generateConversationsPublicToken(values.currentTeam?.id)
            actions.updateCurrentTeam(response)
            lemonToast.success('New token generated')
        },
        saveDomain: ({ value, editingIndex }) => {
            const trimmedValue = value.trim()
            if (!trimmedValue) {
                return
            }

            const newDomains = [...values.conversationsDomains]
            if (editingIndex !== null) {
                newDomains[editingIndex] = trimmedValue
            } else {
                newDomains.push(trimmedValue)
            }

            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    widget_domains: newDomains,
                },
            })
        },
        removeDomain: ({ index }) => {
            const newDomains = values.conversationsDomains.filter((_, i) => i !== index)
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    widget_domains: newDomains,
                },
            })
        },
        startEditDomain: ({ index }) => {
            actions.setEditingDomainIndex(index)
            actions.setDomainInputValue(values.conversationsDomains[index])
        },
        saveGreetingText: () => {
            const trimmedValue = values.greetingInputValue?.trim()
            if (!trimmedValue) {
                return
            }
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    widget_greeting_text: trimmedValue,
                },
            })
        },
        saveIdentificationFormTitle: () => {
            const trimmedValue = values.identificationFormTitleValue?.trim()
            if (!trimmedValue) {
                return
            }
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    widget_identification_form_title: trimmedValue,
                },
            })
        },
        saveIdentificationFormDescription: () => {
            const trimmedValue = values.identificationFormDescriptionValue?.trim()
            if (!trimmedValue) {
                return
            }
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    widget_identification_form_description: trimmedValue,
                },
            })
        },
        savePlaceholderText: () => {
            const trimmedValue = values.placeholderTextValue?.trim()
            if (!trimmedValue) {
                return
            }
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    widget_placeholder_text: trimmedValue,
                },
            })
        },
        setNotificationRecipients: ({ users }) => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    notification_recipients: users.map((u) => u.id),
                },
            })
        },
        setSlackIntegration: ({ integration }) => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    slack_integration_id: integration?.id ?? null,
                    // Clear channel when changing integration
                    slack_channel_id: null,
                    slack_channel_name: null,
                },
            })
            if (integration) {
                actions.loadSlackChannels(integration.id)
            }
        },
        setSlackChannel: ({ channelId, channelName }) => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    slack_channel_id: channelId,
                    slack_channel_name: channelName,
                },
            })
        },
        saveSlackBotToken: async () => {
            const token = values.slackBotTokenValue?.trim()
            if (token) {
                await actions.updateCurrentTeam({
                    conversations_settings: {
                        ...values.currentTeam?.conversations_settings,
                        slack_bot_token: token,
                        // Also set integration_id to a placeholder so handlers know Slack is configured
                        slack_integration_id: -1,
                    },
                })
                lemonToast.success('Slack bot token saved')
                // Load channels after saving token
                actions.loadSlackChannelsWithToken()
            }
        },
        saveSlackTicketEmoji: () => {
            const emoji = values.slackTicketEmojiValue
            if (emoji !== null) {
                actions.updateCurrentTeam({
                    conversations_settings: {
                        ...values.currentTeam?.conversations_settings,
                        slack_ticket_emoji: emoji,
                    },
                })
                lemonToast.success('Ticket emoji saved')
            }
        },
        disconnectSlack: () => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    slack_integration_id: null,
                    slack_channel_id: null,
                    slack_channel_name: null,
                    slack_ticket_emoji: null,
                    slack_bot_token: null,
                },
            })
            lemonToast.success('Slack disconnected')
        },
        updateCurrentTeamSuccess: () => {
            actions.setGreetingInputValue(null)
            actions.setIdentificationFormTitleValue(null)
            actions.setIdentificationFormDescriptionValue(null)
            actions.setPlaceholderTextValue(null)
            actions.setSlackTicketEmojiValue(null)
            actions.setSlackBotTokenValue(null)
        },
    })),
    afterMount(({ values, actions }) => {
        // Load channels if bot token is already configured
        if (values.slackBotToken) {
            actions.loadSlackChannelsWithToken()
        } else {
            // Fallback for legacy integration-based setup
            const integrationId = values.currentTeam?.conversations_settings?.slack_integration_id
            if (integrationId && integrationId > 0) {
                actions.loadSlackChannels(integrationId)
            }
        }
    }),
])
