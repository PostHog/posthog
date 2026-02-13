import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { SlackChannelType, UserBasicType } from '~/types'

import type { supportSettingsLogicType } from './supportSettingsLogicType'

export const supportSettingsLogic = kea<supportSettingsLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'settings', 'supportSettingsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
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
        connectSlack: (nextPath: string) => ({ nextPath }),
        setSlackChannel: (channelId: string | null, channelName: string | null) => ({ channelId, channelName }),
        loadSlackChannelsWithToken: true,
        setSlackTicketEmojiValue: (value: string | null) => ({ value }),
        saveSlackTicketEmoji: true,
        disconnectSlack: true,
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
    }),
    loaders(({ values }) => ({
        slackChannels: [
            [] as SlackChannelType[],
            {
                loadSlackChannelsWithToken: async () => {
                    try {
                        const response = await api.create(`api/conversations/v1/slack/channels`, {})
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
        slackEnabled: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam?.conversations_settings?.slack_enabled,
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
        slackConnected: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam?.conversations_settings?.slack_enabled,
        ],
    }),
    listeners(({ values, actions }) => ({
        connectSlack: ({ nextPath }) => {
            const query = encodeURIComponent(nextPath)
            window.location.href = `/api/conversations/v1/slack/authorize?next=${query}`
        },
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
        setSlackChannel: ({ channelId, channelName }) => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    slack_enabled: true,
                    slack_channel_id: channelId,
                    slack_channel_name: channelName,
                },
            })
        },
        saveSlackTicketEmoji: () => {
            const emoji = values.slackTicketEmojiValue
            if (emoji !== null) {
                actions.updateCurrentTeam({
                    conversations_settings: {
                        ...values.currentTeam?.conversations_settings,
                        slack_enabled: true,
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
                    slack_enabled: false,
                    slack_bot_token: null,
                    slack_team_id: null,
                    slack_channel_id: null,
                    slack_channel_name: null,
                    slack_ticket_emoji: null,
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
        },
    })),
    afterMount(({ values, actions }) => {
        if (values.slackConnected) {
            actions.loadSlackChannelsWithToken()
        }
    }),
])
