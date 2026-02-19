import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { UserBasicType } from '~/types'

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
    }),
    selectors({
        conversationsDomains: [
            (s) => [s.currentTeam],
            (currentTeam): string[] => currentTeam?.conversations_settings?.widget_domains || [],
        ],
        notificationRecipients: [
            (s) => [s.currentTeam],
            (currentTeam): number[] => currentTeam?.conversations_settings?.notification_recipients || [],
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
        updateCurrentTeamSuccess: () => {
            actions.setGreetingInputValue(null)
            actions.setIdentificationFormTitleValue(null)
            actions.setIdentificationFormDescriptionValue(null)
            actions.setPlaceholderTextValue(null)
        },
    })),
])
