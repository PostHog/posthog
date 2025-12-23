import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { Conversation, ConversationDetail, SidePanelTab } from '~/types'

import { TOOL_DEFINITIONS, ToolRegistration } from './max-constants'
import type { maxGlobalLogicType } from './maxGlobalLogicType'
import { maxLogic, mergeConversationHistory } from './maxLogic'

/** Tools available everywhere. These CAN be shadowed by contextual tools for scene-specific handling (e.g. to intercept insight creation). */
export const STATIC_TOOLS: ToolRegistration[] = [
    {
        identifier: 'create_insight' as const,
        name: TOOL_DEFINITIONS['create_insight'].name,
        description: TOOL_DEFINITIONS['create_insight'].description,
    },
    {
        identifier: 'execute_sql' as const,
        name: TOOL_DEFINITIONS['execute_sql'].name,
        description: TOOL_DEFINITIONS['execute_sql'].description,
    },
    {
        identifier: 'filter_session_recordings' as const,
        name: TOOL_DEFINITIONS['filter_session_recordings'].name,
        description: TOOL_DEFINITIONS['filter_session_recordings'].description,
    },
    {
        identifier: 'web_search',
        name: TOOL_DEFINITIONS['web_search'].name,
        description: TOOL_DEFINITIONS['web_search'].description,
    },
    {
        identifier: 'create_dashboard' as const,
        name: TOOL_DEFINITIONS['create_dashboard'].name,
        description: TOOL_DEFINITIONS['create_dashboard'].description,
    },
    {
        identifier: 'search' as const,
        name: TOOL_DEFINITIONS['search'].name,
        description: TOOL_DEFINITIONS['search'].description,
    },
    {
        identifier: 'create_task' as const,
        name: TOOL_DEFINITIONS['create_task'].name,
        description: TOOL_DEFINITIONS['create_task'].description,
    },
    {
        identifier: 'run_task' as const,
        name: TOOL_DEFINITIONS['run_task'].name,
        description: TOOL_DEFINITIONS['run_task'].description,
    },
    {
        identifier: 'get_task_run' as const,
        name: TOOL_DEFINITIONS['get_task_run'].name,
        description: TOOL_DEFINITIONS['get_task_run'].description,
    },
    {
        identifier: 'get_task_run_logs' as const,
        name: TOOL_DEFINITIONS['get_task_run_logs'].name,
        description: TOOL_DEFINITIONS['get_task_run_logs'].description,
    },
    {
        identifier: 'list_tasks' as const,
        name: TOOL_DEFINITIONS['list_tasks'].name,
        description: TOOL_DEFINITIONS['list_tasks'].description,
    },
    {
        identifier: 'list_task_runs' as const,
        name: TOOL_DEFINITIONS['list_task_runs'].name,
        description: TOOL_DEFINITIONS['list_task_runs'].description,
    },
]

export const maxGlobalLogic = kea<maxGlobalLogicType>([
    path(['scenes', 'max', 'maxGlobalLogic']),
    connect(() => ({
        values: [
            organizationLogic,
            ['currentOrganization'],
            sceneLogic,
            ['sceneId', 'sceneConfig'],
            featureFlagLogic,
            ['featureFlags'],
            sidePanelStateLogic,
            ['sidePanelOpen', 'selectedTab'],
        ],
        actions: [router, ['locationChanged'], sidePanelStateLogic, ['openSidePanel']],
    })),
    actions({
        openSidePanelMax: (conversationId?: string) => ({ conversationId }),
        askSidePanelMax: (prompt: string) => ({ prompt }),
        acceptDataProcessing: (testOnlyOverride?: boolean) => ({ testOnlyOverride }),
        registerTool: (tool: ToolRegistration) => ({ tool }),
        deregisterTool: (key: string) => ({ key }),
        prependOrReplaceConversation: (conversation: ConversationDetail | Conversation) => ({ conversation }),
    }),

    loaders(({ values }) => ({
        conversationHistory: [
            [] as ConversationDetail[],
            {
                loadConversationHistory: async (
                    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- Used for conversation restoration
                    _?: {
                        /** If true, the current thread will not be updated with the retrieved conversation. */
                        doNotUpdateCurrentThread?: boolean
                    }
                ) => {
                    const response = await api.conversations.list()
                    return response.results
                },

                loadConversation: async (conversationId: string) => {
                    const response = await api.conversations.get(conversationId)
                    const itemIndex = values.conversationHistory.findIndex((c) => c.id === conversationId)

                    if (itemIndex !== -1) {
                        return [
                            ...values.conversationHistory.slice(0, itemIndex),
                            response,
                            ...values.conversationHistory.slice(itemIndex + 1),
                        ]
                    }
                    return [response, ...values.conversationHistory]
                },
            },
        ],
    })),

    reducers({
        conversationHistory: {
            prependOrReplaceConversation: (state, { conversation }) => {
                return mergeConversationHistory(state, conversation)
            },
        },
        registeredToolMap: [
            {} as Record<string, ToolRegistration>,
            {
                registerTool: (state, { tool }) => ({
                    ...state,
                    [tool.identifier]: tool,
                }),
                deregisterTool: (state, { key }) => {
                    const newState = { ...state }
                    delete newState[key]
                    return newState
                },
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        acceptDataProcessing: async ({ testOnlyOverride }) => {
            await organizationLogic.asyncActions.updateOrganization({
                is_ai_data_processing_approved: testOnlyOverride ?? true,
            })
        },
        askSidePanelMax: ({ prompt }) => {
            let logic = maxLogic.findMounted({ tabId: 'sidepanel' })
            if (!logic) {
                logic = maxLogic({ tabId: 'sidepanel' })
                logic.mount() // we're never unmounting this
            }
            actions.openSidePanelMax()
            // HACK: Delay to ensure maxThreadLogic is mounted after the side panel opens - ugly, but works
            window.setTimeout(() => logic!.actions.askMax(prompt), 100)
        },
        openSidePanelMax: ({ conversationId }) => {
            if (!values.sidePanelOpen || values.selectedTab !== SidePanelTab.Max) {
                actions.openSidePanel(SidePanelTab.Max)
            }
            if (conversationId) {
                let logic = maxLogic.findMounted({ tabId: 'sidepanel' })
                if (!logic) {
                    logic = maxLogic({ tabId: 'sidepanel' })
                    logic.mount() // we're never unmounting this
                }
                logic.actions.openConversation(conversationId)
            }
        },
        loadConversationHistoryFailure: ({ errorObject }) => {
            lemonToast.error(errorObject?.data?.detail || 'Failed to load conversation history.')
        },
    })),
    selectors({
        dataProcessingAccepted: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean => !!currentOrganization?.is_ai_data_processing_approved,
        ],
        dataProcessingApprovalDisabledReason: [
            (s) => [s.currentOrganization],
            (currentOrganization): string | null =>
                !currentOrganization?.membership_level ||
                currentOrganization.membership_level < OrganizationMembershipLevel.Admin
                    ? `Ask an admin or owner of ${currentOrganization?.name} to approve this`
                    : null,
        ],
        availableStaticTools: [
            (s) => [s.featureFlags],
            (featureFlags): ToolRegistration[] => {
                const staticTools = STATIC_TOOLS.filter((tool) => {
                    // Only register the static tools that either aren't flagged or have their flag enabled
                    const toolDefinition = TOOL_DEFINITIONS[tool.identifier]
                    return !toolDefinition.flag || featureFlags[toolDefinition.flag]
                })
                return staticTools
            },
        ],
        toolMap: [
            (s) => [s.registeredToolMap, s.availableStaticTools],
            (registeredToolMap, availableStaticTools) => ({
                ...Object.fromEntries(availableStaticTools.map((tool) => [tool.identifier, tool])),
                ...registeredToolMap,
            }),
        ],
        tools: [(s) => [s.toolMap], (toolMap): ToolRegistration[] => Object.values(toolMap)],
        editInsightToolRegistered: [
            (s) => [s.registeredToolMap],
            (registeredToolMap) => !!registeredToolMap.create_insight,
        ],
        toolSuggestions: [
            (s) => [s.tools],
            (tools): string[] => {
                const suggestions: string[] = []
                for (const tool of tools) {
                    if (tool.suggestions) {
                        suggestions.push(...tool.suggestions)
                    }
                }
                return suggestions
            },
        ],
    }),
])
