import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { supportSettingsLogicType } from './supportSettingsLogicType'

export const supportSettingsLogic = kea<supportSettingsLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'settings', 'supportSettingsLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam', 'updateCurrentTeamSuccess']],
    }),
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
    }),
    selectors({
        conversationsDomains: [
            (s) => [s.currentTeam],
            (currentTeam): string[] => currentTeam?.conversations_settings?.widget_domains || [],
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
    })),
])
