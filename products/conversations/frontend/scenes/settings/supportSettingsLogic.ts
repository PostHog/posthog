import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { mcpServerInstallationsList } from '@posthog/products-mcp-store/frontend/generated/api'
import type { MCPServerInstallationApi } from '@posthog/products-mcp-store/frontend/generated/api.schemas'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { SlackChannelType, UserBasicType } from '~/types'

import type { supportSettingsLogicType } from './supportSettingsLogicType'

export interface EmailConfigStatus {
    id: string
    from_email: string
    from_name: string
    forwarding_address: string | null
    domain: string
    domain_verified: boolean
    dns_records: Record<string, any> | null
}

export const supportSettingsLogic = kea<supportSettingsLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'settings', 'supportSettingsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam', 'currentTeamLoading'], userLogic, ['user']],
        actions: [
            teamLogic,
            ['updateCurrentTeam', 'updateCurrentTeamSuccess', 'updateCurrentTeamFailure', 'loadCurrentTeam'],
        ],
    })),
    actions({
        generateNewToken: true,
        setConversationsEnabledLoading: (loading: boolean) => ({ loading }),
        setWidgetEnabledLoading: (loading: boolean) => ({ loading }),
        // Domain management actions
        setIsAddingDomain: (isAdding: boolean) => ({ isAdding }),
        setEditingDomainIndex: (index: number | null) => ({ index }),
        setDomainInputValue: (value: string) => ({ value }),
        saveDomain: (value: string, editingIndex: number | null) => ({
            value,
            editingIndex,
        }),
        removeDomain: (index: number) => ({ index }),
        startEditDomain: (index: number) => ({ index }),
        cancelDomainEdit: true,
        setGreetingInputValue: (value: string | null) => ({ value }),
        saveGreetingText: true,
        // Identification form settings
        setIdentificationFormTitleValue: (value: string | null) => ({ value }),
        saveIdentificationFormTitle: true,
        setIdentificationFormDescriptionValue: (value: string | null) => ({
            value,
        }),
        saveIdentificationFormDescription: true,
        setPlaceholderTextValue: (value: string | null) => ({ value }),
        savePlaceholderText: true,
        // Notification recipients
        setNotificationRecipients: (users: UserBasicType[]) => ({ users }),
        // Slack channel settings (SupportHog)
        connectSlack: (nextPath: string) => ({ nextPath }),
        setSlackChannels: (channelIds: string[]) => ({ channelIds }),
        loadSlackChannelsWithToken: true,
        setSlackTicketEmojiValue: (value: string | null) => ({ value }),
        saveSlackTicketEmoji: true,
        setSlackBotIconUrlValue: (value: string | null) => ({ value }),
        setSlackBotDisplayNameValue: (value: string | null) => ({ value }),
        saveSlackBotSettings: true,
        setSlackNotifyOnJoin: (enabled: boolean) => ({ enabled }),
        setSlackNotifyOnLeave: (enabled: boolean) => ({ enabled }),
        setSlackNudgeEnabled: (enabled: boolean) => ({ enabled }),
        setSlackAlertChannel: (channelId: string | null) => ({ channelId }),
        disconnectSlack: true,
        // Teams channel settings
        connectTeams: (nextPath: string) => ({ nextPath }),
        disconnectTeams: true,
        loadTeamsTeamsWithToken: true,
        loadTeamsChannelsForTeam: (teamId: string) => ({ teamId }),
        installTeamsApp: (teamId: string) => ({ teamId }),
        setTeamsInstallStatus: (
            status: 'idle' | 'installing' | 'installed' | 'needs_org_catalog' | 'error',
            teamId: string | null = null
        ) => ({ status, teamId }),
        // Multi-channel Teams actions
        addTeamsChannelPair: (teamId: string, channelId: string) => ({
            teamId,
            channelId,
        }),
        removeTeamsChannelPair: (channelId: string) => ({ channelId }),
        setTeamsChannelPairLoading: (channelId: string | null) => ({
            channelId,
        }),
        cacheTeamsChannelsForTeam: (
            teamId: string,
            channels: {
                id: string
                name: string
                membership_type?: string | null
            }[]
        ) => ({ teamId, channels }),
        // Email channel settings (multi-config)
        loadEmailConfigs: true,
        loadEmailConfigsDone: (configs: EmailConfigStatus[]) => ({ configs }),
        setAddEmailFormVisible: (visible: boolean) => ({ visible }),
        setNewEmailFromEmail: (value: string) => ({ value }),
        setNewEmailFromName: (value: string) => ({ value }),
        connectEmail: true,
        connectEmailDone: (config: EmailConfigStatus | null) => ({ config }),
        disconnectEmail: (configId: string) => ({ configId }),
        disconnectEmailDone: (configId: string) => ({ configId }),
        verifyEmailDomain: (configId: string) => ({ configId }),
        verifyEmailDomainDone: (configId: string, verified: boolean, dnsRecords: Record<string, any> | null) => ({
            configId,
            verified,
            dnsRecords,
        }),
        sendTestEmail: (configId: string) => ({ configId }),
        sendTestEmailDone: (configId: string) => ({ configId }),
        // GitHub Issues channel settings
        connectGithub: (integrationId: number) => ({ integrationId }),
        disconnectGithub: true,
        setGithubRepos: (repos: string[]) => ({ repos }),
        loadGithubRepos: true,
        // AI suggestions
        setAiSuggestionsEnabled: (enabled: boolean) => ({ enabled }),
        setAiSuggestionsLoading: (loading: boolean) => ({ loading }),
        setAiDiagnosticsEnabled: (enabled: boolean) => ({ enabled }),
        setAiDiagnosticsLoading: (loading: boolean) => ({ loading }),
        setAiResolutionChannels: (channels: string[]) => ({ channels }),
        setAiReplyMode: (channel: string, ticketType: string, mode: 'private_note' | 'bot_reply') => ({
            channel,
            ticketType,
            mode,
        }),
        setAiMcpInstallations: (ids: string[]) => ({ ids }),
        setAiMcpInstallationsLoading: (loading: boolean) => ({ loading }),
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
        // Email multi-config state
        emailConfigs: [
            [] as EmailConfigStatus[],
            {
                loadEmailConfigsDone: (_, { configs }) => configs,
                connectEmailDone: (state, { config }) => (config ? [...state, config] : state),
                disconnectEmailDone: (state, { configId }) => state.filter((c) => c.id !== configId),
                verifyEmailDomainDone: (state, { configId, verified, dnsRecords }) => {
                    const targetDomain = state.find((t) => t.id === configId)?.domain
                    if (!targetDomain) {
                        return state
                    }
                    return state.map((c) =>
                        c.domain === targetDomain
                            ? {
                                  ...c,
                                  domain_verified: verified,
                                  dns_records: dnsRecords ?? c.dns_records,
                              }
                            : c
                    )
                },
            },
        ],
        addEmailFormVisible: [
            false,
            {
                setAddEmailFormVisible: (_, { visible }) => visible,
                connectEmailDone: (state, { config }) => (config ? false : state),
            },
        ],
        newEmailFromEmail: [
            '',
            {
                setNewEmailFromEmail: (_, { value }) => value,
                connectEmailDone: (state, { config }) => (config ? '' : state),
            },
        ],
        newEmailFromName: [
            '',
            {
                setNewEmailFromName: (_, { value }) => value,
                connectEmailDone: (state, { config }) => (config ? '' : state),
            },
        ],
        emailConnecting: [
            false,
            {
                connectEmail: () => true,
                connectEmailDone: () => false,
            },
        ],
        emailVerifyingConfigId: [
            null as string | null,
            {
                verifyEmailDomain: (_, { configId }) => configId,
                verifyEmailDomainDone: () => null,
            },
        ],
        emailTestingConfigId: [
            null as string | null,
            {
                sendTestEmail: (_, { configId }) => configId,
                sendTestEmailDone: () => null,
            },
        ],
        teamsInstallStatus: [
            'idle' as 'idle' | 'installing' | 'installed' | 'needs_org_catalog' | 'error',
            {
                installTeamsApp: () => 'installing' as const,
                setTeamsInstallStatus: (_, { status }) => status,
                disconnectTeams: () => 'idle' as const,
            },
        ],
        teamsInstallingForTeamId: [
            null as string | null,
            {
                installTeamsApp: (_, { teamId }) => teamId,
                setTeamsInstallStatus: (_, { teamId }) => teamId,
                disconnectTeams: () => null,
            },
        ],
        teamsChannelsCache: [
            {} as Record<string, { id: string; name: string; membership_type?: string | null }[]>,
            {
                cacheTeamsChannelsForTeam: (state, { teamId, channels }) => ({
                    ...state,
                    [teamId]: channels,
                }),
                disconnectTeams: () => ({}),
            },
        ],
        teamsChannelPairLoading: [
            null as string | null,
            {
                setTeamsChannelPairLoading: (_, { channelId }) => channelId,
                addTeamsChannelPair: (_, { channelId }) => channelId,
                removeTeamsChannelPair: (_, { channelId }) => channelId,
            },
        ],
        aiSuggestionsLoading: [
            false,
            {
                setAiSuggestionsLoading: (_, { loading }) => loading,
                updateCurrentTeamSuccess: () => false,
                updateCurrentTeamFailure: () => false,
            },
        ],
        aiDiagnosticsLoading: [
            false,
            {
                setAiDiagnosticsLoading: (_, { loading }) => loading,
                updateCurrentTeamSuccess: () => false,
                updateCurrentTeamFailure: () => false,
            },
        ],
        aiMcpInstallationsLoading: [
            false,
            {
                setAiMcpInstallationsLoading: (_, { loading }) => loading,
                updateCurrentTeamSuccess: () => false,
                updateCurrentTeamFailure: () => false,
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
    loaders(({ actions, values }) => ({
        githubIntegrations: [
            [] as { id: number; name: string }[],
            {
                loadGithubIntegrations: async () => {
                    try {
                        const response = await api.integrations.list()
                        return (response.results || [])
                            .filter((i: any) => i.kind === 'github')
                            .map((i: any) => ({
                                id: i.id,
                                name: i.config?.account?.name || `Installation #${i.id}`,
                            }))
                    } catch {
                        return values.githubIntegrations
                    }
                },
            },
        ],
        githubRepos: [
            [] as { full_name: string; name: string }[],
            {
                loadGithubRepos: async () => {
                    try {
                        // nosemgrep: prefer-codegen-api
                        const response = await api.create('api/conversations/v1/github/repos', {})
                        return response.repos || []
                    } catch {
                        lemonToast.error('Failed to load GitHub repositories')
                        return values.githubRepos
                    }
                },
            },
        ],
        slackChannels: [
            [] as SlackChannelType[],
            {
                loadSlackChannelsWithToken: async () => {
                    try {
                        // nosemgrep: prefer-codegen-api
                        const response = await api.create(`api/conversations/v1/slack/channels`, {})
                        return response.channels || []
                    } catch {
                        lemonToast.error('Failed to load Slack channels')
                        return values.slackChannels
                    }
                },
            },
        ],
        teamsTeams: [
            [] as { id: string; name: string }[],
            {
                loadTeamsTeamsWithToken: async () => {
                    try {
                        // nosemgrep: prefer-codegen-api
                        const response = await api.create('api/conversations/v1/teams/teams', {})
                        return response.teams || []
                    } catch {
                        lemonToast.error('Failed to load Teams groups')
                        return values.teamsTeams
                    }
                },
            },
        ],
        teamsChannels: [
            [] as {
                id: string
                name: string
                membership_type?: string | null
            }[],
            {
                loadTeamsChannelsForTeam: async ({ teamId }: { teamId: string }) => {
                    try {
                        // nosemgrep: prefer-codegen-api
                        const response = await api.create('api/conversations/v1/teams/channels', {
                            team_id: teamId,
                        })
                        const channels = response.channels || []
                        // Also cache for multi-channel UI
                        actions.cacheTeamsChannelsForTeam(teamId, channels)
                        return channels
                    } catch {
                        lemonToast.error('Failed to load Teams channels')
                        return values.teamsChannels
                    }
                },
            },
        ],
        mcpInstallations: [
            [] as MCPServerInstallationApi[],
            {
                loadMcpInstallations: async () => {
                    const projectId = values.currentTeam?.id
                    if (!projectId) {
                        return []
                    }
                    try {
                        const response = await mcpServerInstallationsList(String(projectId))
                        return response.results ?? []
                    } catch {
                        lemonToast.error('Failed to load MCP installations')
                        return values.mcpInstallations
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
        slackChannelIds: [
            (s) => [s.currentTeam],
            (currentTeam): string[] => {
                const cs = currentTeam?.conversations_settings
                if (Array.isArray(cs?.slack_channel_ids)) {
                    return cs.slack_channel_ids
                }
                return cs?.slack_channel_id ? [cs.slack_channel_id] : []
            },
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
        slackNotifyOnJoin: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam?.conversations_settings?.slack_notify_on_join,
        ],
        slackNotifyOnLeave: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam?.conversations_settings?.slack_notify_on_leave,
        ],
        slackNudgeEnabled: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => currentTeam?.conversations_settings?.slack_nudge_enabled ?? true,
        ],
        slackAlertChannelId: [
            (s) => [s.currentTeam],
            (currentTeam): string | null => currentTeam?.conversations_settings?.slack_alert_channel_id ?? null,
        ],
        emailConnected: [(s) => [s.emailConfigs], (emailConfigs): boolean => emailConfigs.length > 0],
        teamsConnected: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam?.conversations_settings?.teams_enabled,
        ],
        teamsTeamId: [
            (s) => [s.currentTeam],
            (currentTeam): string | null => currentTeam?.conversations_settings?.teams_team_id ?? null,
        ],
        teamsTeamName: [
            (s) => [s.currentTeam],
            (currentTeam): string | null => currentTeam?.conversations_settings?.teams_team_name ?? null,
        ],
        teamsChannelId: [
            (s) => [s.currentTeam],
            (currentTeam): string | null => currentTeam?.conversations_settings?.teams_channel_id ?? null,
        ],
        teamsChannelName: [
            (s) => [s.currentTeam],
            (currentTeam): string | null => currentTeam?.conversations_settings?.teams_channel_name ?? null,
        ],
        teamsChannelPairs: [
            (s) => [s.currentTeam],
            (
                currentTeam
            ): {
                team_id: string
                team_name?: string | null
                channel_id: string
                channel_name?: string | null
                membership_type?: string | null
            }[] => {
                const cs = currentTeam?.conversations_settings
                if (Array.isArray(cs?.teams_channels) && cs.teams_channels.length > 0) {
                    return cs.teams_channels
                }
                // Fallback to legacy scalar fields
                if (cs?.teams_team_id && cs?.teams_channel_id) {
                    return [
                        {
                            team_id: cs.teams_team_id,
                            team_name: cs.teams_team_name,
                            channel_id: cs.teams_channel_id,
                            channel_name: cs.teams_channel_name,
                        },
                    ]
                }
                return []
            },
        ],
        githubConnected: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam?.conversations_settings?.github_enabled,
        ],
        githubSelectedRepos: [
            (s) => [s.currentTeam],
            (currentTeam): string[] => currentTeam?.conversations_settings?.github_repos || [],
        ],
        aiSuggestionsEnabled: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam?.conversations_settings?.ai_suggestions_enabled,
        ],
        aiDiagnosticsEnabled: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam?.conversations_settings?.ai_diagnostics_enabled,
        ],
        aiEnabledChannels: [
            (s) => [s.currentTeam, s.emailConfigs],
            (currentTeam, emailConfigs): string[] => {
                const cs = currentTeam?.conversations_settings
                if (!cs) {
                    return []
                }
                const channels: string[] = []
                channels.push('widget')
                if (cs.slack_enabled) {
                    channels.push('slack')
                }
                if (emailConfigs.length > 0 || cs.email_enabled) {
                    channels.push('email')
                }
                if (cs.teams_enabled) {
                    channels.push('teams')
                }
                if (cs.github_enabled) {
                    channels.push('github')
                }
                return channels
            },
        ],
        aiResolutionChannels: [
            (s) => [s.currentTeam, s.aiEnabledChannels],
            (currentTeam, aiEnabledChannels): string[] => {
                const stored = currentTeam?.conversations_settings?.ai_resolution_channels
                if (Array.isArray(stored)) {
                    return stored.filter((ch: string) => aiEnabledChannels.includes(ch))
                }
                return aiEnabledChannels
            },
        ],
        aiReplyModes: [
            (s) => [s.currentTeam],
            (currentTeam): Record<string, Record<string, 'private_note' | 'bot_reply'>> => {
                return currentTeam?.conversations_settings?.ai_reply_modes ?? {}
            },
        ],
        aiMcpInstallationIds: [
            (s) => [s.currentTeam],
            (currentTeam): string[] => currentTeam?.conversations_settings?.ai_mcp_installation_ids ?? [],
        ],
    }),
    listeners(({ values, actions }) => ({
        connectSlack: async ({ nextPath }) => {
            const query = encodeURIComponent(nextPath)
            // nosemgrep: prefer-codegen-api
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
        setSlackChannels: ({ channelIds }) => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    slack_channel_ids: channelIds,
                    // Transitional: keep legacy key for old frontend bundles
                    slack_channel_id: channelIds[0] ?? null,
                    slack_channel_name: null,
                },
            })
        },
        setSlackNotifyOnJoin: ({ enabled }) => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    slack_notify_on_join: enabled,
                },
            })
        },
        setSlackNotifyOnLeave: ({ enabled }) => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    slack_notify_on_leave: enabled,
                },
            })
        },
        setSlackNudgeEnabled: ({ enabled }) => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    slack_nudge_enabled: enabled,
                },
            })
        },
        setSlackAlertChannel: ({ channelId }) => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    slack_alert_channel_id: channelId,
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
        // Email multi-config listeners
        loadEmailConfigs: async () => {
            try {
                // nosemgrep: prefer-codegen-api
                const response = await api.get('api/conversations/v1/email/status')
                actions.loadEmailConfigsDone(response.configs || [])
            } catch {
                actions.loadEmailConfigsDone([])
            }
        },
        connectEmail: async () => {
            const { newEmailFromEmail, newEmailFromName } = values
            if (!newEmailFromEmail || !newEmailFromName) {
                lemonToast.error('Please enter both an email address and display name')
                actions.connectEmailDone(null)
                return
            }
            try {
                // nosemgrep: prefer-codegen-api
                const response = await api.create('api/conversations/v1/email/connect', {
                    from_email: newEmailFromEmail,
                    from_name: newEmailFromName,
                })
                actions.connectEmailDone(response.config)
                actions.updateCurrentTeam({
                    conversations_settings: {
                        ...values.currentTeam?.conversations_settings,
                        email_enabled: true,
                    },
                })
                lemonToast.success('Email address connected')
            } catch {
                lemonToast.error('Failed to connect email')
                actions.connectEmailDone(null)
            }
        },
        disconnectEmail: async ({ configId }) => {
            try {
                // nosemgrep: prefer-codegen-api
                await api.create('api/conversations/v1/email/disconnect', {
                    config_id: configId,
                })
            } catch {
                lemonToast.error('Failed to disconnect email')
                return
            }
            const wasLast = values.emailConfigs.length === 1
            actions.disconnectEmailDone(configId)
            if (wasLast) {
                actions.updateCurrentTeam({
                    conversations_settings: {
                        ...values.currentTeam?.conversations_settings,
                        email_enabled: false,
                    },
                })
            }
            lemonToast.success('Email address disconnected')
        },
        verifyEmailDomain: async ({ configId }) => {
            try {
                // nosemgrep: prefer-codegen-api
                const response = await api.create('api/conversations/v1/email/verify-domain', {
                    config_id: configId,
                })
                actions.verifyEmailDomainDone(configId, response.domain_verified, response.dns_records || null)
                if (response.domain_verified) {
                    lemonToast.success('Domain verified successfully! Outbound email is now active.')
                } else {
                    lemonToast.warning('Domain not yet verified. Please check your DNS records and try again.')
                }
            } catch {
                lemonToast.error('Failed to verify domain')
                actions.verifyEmailDomainDone(configId, false, null)
            }
        },
        sendTestEmail: async ({ configId }) => {
            try {
                // nosemgrep: prefer-codegen-api
                const response = await api.create('api/conversations/v1/email/send-test', {
                    config_id: configId,
                })
                actions.sendTestEmailDone(configId)
                lemonToast.success(`Test email sent to ${response.sent_to}`)
            } catch {
                lemonToast.error('Failed to send test email. Check SMTP settings.')
                actions.sendTestEmailDone(configId)
            }
        },
        disconnectSlack: async () => {
            try {
                // nosemgrep: prefer-codegen-api
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
        connectTeams: async ({ nextPath }) => {
            try {
                const query = encodeURIComponent(nextPath)
                // nosemgrep: prefer-codegen-api
                const response = await api.get(`api/conversations/v1/teams/authorize?next=${query}`)
                window.location.href = response.url
            } catch {
                lemonToast.error('Failed to start Microsoft Teams authorization')
            }
        },
        disconnectTeams: async () => {
            try {
                // nosemgrep: prefer-codegen-api
                await api.create('api/conversations/v1/teams/disconnect', {})
            } catch {
                lemonToast.error('Failed to disconnect Microsoft Teams')
                return
            }

            actions.loadCurrentTeam()
            lemonToast.success('Microsoft Teams disconnected')
        },
        installTeamsApp: async ({ teamId }) => {
            try {
                // nosemgrep: prefer-codegen-api
                const response = await api.create('api/conversations/v1/teams/install', {
                    team_id: teamId,
                })
                if (response?.ok) {
                    actions.setTeamsInstallStatus('installed', teamId)
                    actions.loadTeamsChannelsForTeam(teamId)
                } else {
                    actions.setTeamsInstallStatus('error', teamId)
                    lemonToast.error('Failed to install SupportHog in the selected Teams group')
                }
            } catch (err: any) {
                const detail = err?.data?.error ?? err?.detail ?? ''
                if (detail === 'app_not_found_in_catalog') {
                    actions.setTeamsInstallStatus('needs_org_catalog', teamId)
                    return
                }
                if (detail === 'catalog_not_configured') {
                    actions.setTeamsInstallStatus('error', teamId)
                    lemonToast.error(
                        'SupportHog Teams app is not configured on this PostHog instance. Contact your administrator.'
                    )
                    return
                }
                actions.setTeamsInstallStatus('error', teamId)
                lemonToast.error('Failed to install SupportHog in the selected Teams group')
            }
        },
        addTeamsChannelPair: async ({ teamId, channelId }) => {
            try {
                // nosemgrep: prefer-codegen-api
                await api.create('api/conversations/v1/teams/select-channel', {
                    action: 'add',
                    team_id: teamId,
                    channel_id: channelId,
                })
            } catch (err: any) {
                const detail = err?.data?.error ?? ''
                if (detail === 'max_channels_exceeded') {
                    lemonToast.error('Maximum number of Teams channels reached')
                } else {
                    lemonToast.error('Failed to add Teams channel')
                }
                actions.setTeamsChannelPairLoading(null)
                return
            }
            actions.loadCurrentTeam()
            actions.setTeamsChannelPairLoading(null)
            // Install app in the team group if not already installed
            actions.installTeamsApp(teamId)
        },
        removeTeamsChannelPair: async ({ channelId }) => {
            try {
                // nosemgrep: prefer-codegen-api
                await api.create('api/conversations/v1/teams/select-channel', {
                    action: 'remove',
                    channel_id: channelId,
                })
            } catch {
                lemonToast.error('Failed to remove Teams channel')
                actions.setTeamsChannelPairLoading(null)
                return
            }
            actions.loadCurrentTeam()
            actions.setTeamsChannelPairLoading(null)
        },
        setAiSuggestionsEnabled: ({ enabled }) => {
            actions.setAiSuggestionsLoading(true)
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    ai_suggestions_enabled: enabled,
                },
            })
            if (enabled) {
                actions.loadMcpInstallations()
            }
        },
        setAiDiagnosticsEnabled: ({ enabled }) => {
            actions.setAiDiagnosticsLoading(true)
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    ai_diagnostics_enabled: enabled,
                },
            })
        },
        setAiResolutionChannels: ({ channels }) => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    ai_resolution_channels: channels,
                },
            })
        },
        setAiReplyMode: ({ channel, ticketType, mode }) => {
            const current = values.currentTeam?.conversations_settings?.ai_reply_modes ?? {}
            const channelModes = { ...current[channel], [ticketType]: mode }
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    ai_reply_modes: { ...current, [channel]: channelModes },
                },
            })
        },
        setAiMcpInstallations: ({ ids }) => {
            const userId = values.user?.id
            if (!userId || values.aiMcpInstallationsLoading) {
                return
            }
            actions.setAiMcpInstallationsLoading(true)
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    ai_mcp_installation_ids: ids,
                    ai_mcp_run_as_user_id: userId,
                },
            })
        },
        connectGithub: async ({ integrationId }) => {
            try {
                // nosemgrep: prefer-codegen-api
                await api.create('api/conversations/v1/github/connect', {
                    integration_id: integrationId,
                })
                actions.loadCurrentTeam()
                actions.loadGithubRepos()
                lemonToast.success('GitHub connected')
            } catch {
                lemonToast.error('Failed to connect GitHub')
            }
        },
        disconnectGithub: async () => {
            try {
                // nosemgrep: prefer-codegen-api
                await api.create('api/conversations/v1/github/disconnect', {})
                actions.loadCurrentTeam()
                lemonToast.success('GitHub disconnected')
            } catch {
                lemonToast.error('Failed to disconnect GitHub')
            }
        },
        setGithubRepos: async ({ repos }) => {
            try {
                // nosemgrep: prefer-codegen-api
                await api.create('api/conversations/v1/github/select-repos', {
                    repos,
                })
                actions.loadCurrentTeam()
            } catch {
                lemonToast.error('Failed to save repository selection')
            }
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
        if (values.teamsConnected) {
            actions.loadTeamsTeamsWithToken()
            const teamsTeamId = values.teamsTeamId
            if (teamsTeamId) {
                // Already installed on a previous visit — skip the Graph install
                // call (it's idempotent server-side, but avoids a request per page
                // load) and jump straight to loading channels.
                actions.setTeamsInstallStatus('installed', teamsTeamId)
                actions.loadTeamsChannelsForTeam(teamsTeamId)
            }
        }
        // Always load email configs to populate the list
        actions.loadEmailConfigs()
        // Load GitHub integrations for the connect picker
        actions.loadGithubIntegrations()
        if (values.githubConnected) {
            actions.loadGithubRepos()
        }
        if (values.aiSuggestionsEnabled) {
            actions.loadMcpInstallations()
        }
    }),
])
