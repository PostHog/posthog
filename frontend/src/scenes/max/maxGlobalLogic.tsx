import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { Conversation, ConversationDetail, SidePanelTab } from '~/types'

import { conversationsDestroy } from 'products/conversations/frontend/generated/api'

import { TOOL_DEFINITIONS, ToolRegistration } from './max-constants'
import type { maxGlobalLogicType } from './maxGlobalLogicType'
import { SIDE_PANEL_PANEL_ID, maxLogic, mergeConversationHistory, mergeConversations } from './maxLogic'

// Keep this stored across all projects, only display this once per device
const AI_LIABILITY_NOTICE_STORAGE_KEY = 'posthog_ai_liability_notice_dismissed'
const AI_DATA_PROCESSING_DISMISSED_STORAGE_KEY = 'posthog_ai_data_processing_dismissed'

/** Tools available everywhere. These CAN be shadowed by contextual tools for scene-specific handling (e.g. to intercept insight creation). */
export const STATIC_TOOLS: ToolRegistration[] = [
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
            teamLogic,
            ['currentTeamIdStrict'],
            featureFlagLogic,
            ['featureFlags'],
            sidePanelStateLogic,
            ['sidePanelOpen', 'selectedTab'],
            preflightLogic,
            ['preflight', 'isCloudOrDev'],
            userLogic,
            ['user'],
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
        deleteConversation: (id: string) => ({ id }),
        dismissLiabilityNotice: true,
        dismissDataProcessing: true,
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
                    // maxGlobalLogic is mounted globally, so this loader can fire before the session is
                    // resolved (or for an expired/unauthenticated session). Skip the fetch in that case —
                    // an unauthenticated GET /conversations only produces a 401, a misleading toast, and
                    // error-tracking noise. The `user` subscription re-runs this once the session resolves.
                    if (!values.user || !values.isMaxAvailable) {
                        return values.conversationHistory
                    }
                    const response = await api.conversations.list()
                    return response.results.map((conversation) =>
                        mergeConversations(
                            conversation,
                            values.conversationHistory.find((existing) => existing.id === conversation.id)
                        )
                    )
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
        liabilityNoticeDismissed: [
            false,
            { persist: true, storageKey: AI_LIABILITY_NOTICE_STORAGE_KEY },
            {
                dismissLiabilityNotice: () => true,
            },
        ],
        dataProcessingDismissed: [
            false,
            { persist: true, storageKey: AI_DATA_PROCESSING_DISMISSED_STORAGE_KEY },
            {
                dismissDataProcessing: () => true,
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
            newInternalTab(urls.ai(undefined, prompt))
        },
        openSidePanelMax: ({ conversationId }) => {
            if (!values.sidePanelOpen || values.selectedTab !== SidePanelTab.Max) {
                actions.openSidePanel(SidePanelTab.Max)
            }
            if (conversationId) {
                let logic = maxLogic.findMounted({ panelId: SIDE_PANEL_PANEL_ID })
                if (!logic) {
                    logic = maxLogic({ panelId: SIDE_PANEL_PANEL_ID })
                    logic.mount() // we're never unmounting this
                }
                logic.actions.openConversation(conversationId)
            }
        },
        loadConversationHistoryFailure: ({ errorObject }) => {
            // Unauthenticated/expired sessions can still reach here (e.g. session expires mid-request);
            // stay silent rather than showing a confusing toast and generating error-tracking noise.
            if (errorObject?.status === 401 || errorObject?.status === 403) {
                return
            }
            lemonToast.error(errorObject?.data?.detail || 'Failed to load conversation history.')
        },
        deleteConversation: async ({ id }) => {
            try {
                await conversationsDestroy(String(values.currentTeamIdStrict), id)
                if (values.currentConversationId === id) {
                    router.actions.push(urls.aiHistory())
                }
                for (const logic of maxLogic.findAllMounted()) {
                    if (logic.values.conversationId === id) {
                        logic.actions.startNewConversation()
                    }
                }
                actions.loadConversationHistory()
            } catch {
                lemonToast.error('Failed to delete chat')
            }
        },
    })),
    subscriptions(({ actions, values, cache }) => ({
        // Load conversation history once the user is authenticated. maxGlobalLogic is mounted globally,
        // so the session may resolve after mount (or never, for an expired session) — reacting to `user`
        // avoids the unauthenticated fetch while still loading history as soon as auth is available.
        user: (user) => {
            if (user && values.isMaxAvailable && !cache.conversationHistoryLoaded) {
                cache.conversationHistoryLoaded = true
                actions.loadConversationHistory()
            }
        },
    })),
    afterMount(({ actions, values, cache }) => {
        if (values.user && values.isMaxAvailable && !cache.conversationHistoryLoaded) {
            cache.conversationHistoryLoaded = true
            actions.loadConversationHistory()
        }
    }),

    selectors({
        currentConversationId: [
            () => [router.selectors.searchParams],
            (searchParams): string | null => searchParams?.chat ?? null,
        ],
        dataProcessingAccepted: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean => !!currentOrganization?.is_ai_data_processing_approved,
        ],
        // On Cloud/dev a provider key is always present. On a self-hosted (hobby) instance Max only
        // works once ANTHROPIC_API_KEY is configured, so we surface a "set the key" state instead.
        // Treat a not-yet-loaded preflight (null) as available so the empty-state doesn't flash
        // before preflight resolves — once loaded we gate on cloud/dev or the key being present.
        isMaxAvailable: [
            (s) => [s.isCloudOrDev, s.preflight],
            (isCloudOrDev, preflight): boolean => !preflight || !!isCloudOrDev || !!preflight.anthropic_available,
        ],
        dataProcessingApprovalDisabledReason: [
            (s) => [s.currentOrganization],
            (currentOrganization): string | null =>
                !currentOrganization?.membership_level ||
                currentOrganization.membership_level < OrganizationMembershipLevel.Admin
                    ? `Ask an admin or owner of ${currentOrganization?.name} to approve this`
                    : null,
        ],
        isOrganizationCreatedRecently: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean => {
                const orgCreatedAt = currentOrganization?.created_at
                return orgCreatedAt ? dayjs().diff(dayjs(orgCreatedAt), 'day') <= 15 : false
            },
        ],
        shouldShowLiabilityNotice: [
            (s) => [s.isOrganizationCreatedRecently, s.liabilityNoticeDismissed],
            (isOrganizationCreatedRecently, liabilityNoticeDismissed): boolean =>
                isOrganizationCreatedRecently && !liabilityNoticeDismissed,
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
