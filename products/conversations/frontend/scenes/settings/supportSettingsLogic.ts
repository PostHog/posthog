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
        setSlackBotIconUrlValue: (value: string | null) => ({ value }),
        setSlackBotDisplayNameValue: (value: string | null) => ({ value }),
        saveSlackBotSettings: true,
        disconnectSlack: true,
        // Email channel settings
        setEmailFromEmail: (value: string) => ({ value }),
        setEmailFromName: (value: string) => ({ value }),
        connectEmail: true,
        connectEmailDone: (forwardingAddress: string | null) => ({ forwardingAddress }),
        disconnectEmail: true,
        loadEmailStatus: true,
        loadEmailStatusDone: (
            status: { forwarding_address: string | null; from_email: string; from_name: string } | null
        ) => ({
            status,
        }),
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
        emailFromEmail: [
            '' as string,
            {
                setEmailFromEmail: (_, { value }) => value,
            },
        ],
        emailFromName: [
            '' as string,
            {
                setEmailFromName: (_, { value }) => value,
            },
        ],
        emailConnecting: [
            false as boolean,
            {
                connectEmail: () => true,
                connectEmailDone: () => false,
            },
        ],
        emailForwardingAddress: [
            null as string | null,
            {
                connectEmailDone: (_, { forwardingAddress }) => forwardingAddress,
                loadEmailStatusDone: (_, { status }) => status?.forwarding_address ?? null,
                disconnectEmail: () => null,
            },
        ],
        slackTicketEmojiValue: [
            null as string | null,
            {
                setSlackTicketEmojiValue: (_, { value }) => value,
            },
        ],
        slackBotIconUrlValue: [
            null as string | null,
            {
                setSlackBotIconUrlValue: (_, { value }) => value,
            },
        ],
        slackBotDisplayNameValue: [
            null as string | null,
            {
                setSlackBotDisplayNameValue: (_, { value }) => value,
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
        slackBotIconUrl: [
            (s) => [s.currentTeam],
            (currentTeam): string | null => currentTeam?.conversations_settings?.slack_bot_icon_url ?? null,
        ],
        slackBotDisplayName: [
            (s) => [s.currentTeam],
            (currentTeam): string | null => currentTeam?.conversations_settings?.slack_bot_display_name ?? null,
        ],
        emailConnected: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam?.conversations_settings?.email_enabled,
        ],
    }),
    listeners(({ values, actions }) => ({
        connectSlack: async ({ nextPath }) => {
            const query = encodeURIComponent(nextPath)
            const response = await api.get(`api/conversations/v1/slack/authorize?next=${query}`)
            window.location.href = response.url
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
        saveSlackBotSettings: () => {
            const iconUrl = values.slackBotIconUrlValue?.trim()
            const displayName = values.slackBotDisplayNameValue?.trim()
            if (iconUrl && !iconUrl.startsWith('https://')) {
                lemonToast.error('Icon URL must start with https://')
                return
            }
            const updates: Record<string, string | null> = {}
            if (values.slackBotIconUrlValue !== null) {
                updates.slack_bot_icon_url = iconUrl || null
            }
            if (values.slackBotDisplayNameValue !== null) {
                updates.slack_bot_display_name = displayName || null
            }
            if (Object.keys(updates).length > 0) {
                actions.updateCurrentTeam({
                    conversations_settings: {
                        ...values.currentTeam?.conversations_settings,
                        ...updates,
                    },
                })
                lemonToast.success('Bot settings saved')
            }
        },
        loadEmailStatus: async () => {
            try {
                const response = await api.get('api/conversations/v1/email/status')
                if (response.connected) {
                    actions.loadEmailStatusDone({
                        forwarding_address: response.forwarding_address,
                        from_email: response.from_email,
                        from_name: response.from_name,
                    })
                    actions.setEmailFromEmail(response.from_email || '')
                    actions.setEmailFromName(response.from_name || '')
                } else {
                    actions.loadEmailStatusDone(null)
                }
            } catch {
                actions.loadEmailStatusDone(null)
            }
        },
        connectEmail: async () => {
            const { emailFromEmail, emailFromName } = values
            if (!emailFromEmail || !emailFromName) {
                lemonToast.error('Please enter both an email address and display name')
                actions.connectEmailDone(null)
                return
            }
            try {
                const response = await api.create('api/conversations/v1/email/connect', {
                    from_email: emailFromEmail,
                    from_name: emailFromName,
                })
                actions.connectEmailDone(response.forwarding_address)
                actions.updateCurrentTeam({
                    conversations_settings: {
                        ...values.currentTeam?.conversations_settings,
                        email_enabled: true,
                    },
                })
                lemonToast.success('Email channel connected')
            } catch {
                lemonToast.error('Failed to connect email')
                actions.connectEmailDone(null)
            }
        },
        disconnectEmail: async () => {
            try {
                await api.create('api/conversations/v1/email/disconnect', {})
            } catch {
                lemonToast.error('Failed to disconnect email')
                return
            }
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    email_enabled: false,
                },
            })
            actions.setEmailFromEmail('')
            actions.setEmailFromName('')
            lemonToast.success('Email channel disconnected')
        },
        disconnectSlack: async () => {
            try {
                await api.create('api/conversations/v1/slack/disconnect', {})
            } catch {
                lemonToast.error('Failed to disconnect Slack')
                return
            }

            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    slack_enabled: false,
                    slack_channel_id: null,
                    slack_channel_name: null,
                    slack_ticket_emoji: null,
                    slack_bot_icon_url: null,
                    slack_bot_display_name: null,
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
            actions.setSlackBotIconUrlValue(null)
            actions.setSlackBotDisplayNameValue(null)
        },
    })),
    afterMount(({ values, actions }) => {
        if (values.slackConnected) {
            actions.loadSlackChannelsWithToken()
        }
        if (values.emailConnected) {
            actions.loadEmailStatus()
        }
    }),
])
