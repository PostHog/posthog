import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

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

import { sidePanelStateLogic } from '~/layout/navigation/sidepanel/sidePanelStateLogic'
import { Conversation, ConversationDetail, SidePanelTab } from '~/types'

import { conversationsDestroy } from 'products/conversations/frontend/generated/api'
import { requestAiAccessCreate } from 'products/platform_features/frontend/generated/api'

import { TOOL_DEFINITIONS, ToolRegistration } from './max-constants'
import type { maxGlobalLogicType } from './maxGlobalLogicType'
import { SIDE_PANEL_PANEL_ID, maxLogic, mergeConversationHistory, mergeConversations } from './maxLogic'

// Keep this stored across all projects, only display this once per device
const AI_LIABILITY_NOTICE_STORAGE_KEY = 'posthog_ai_liability_notice_dismissed'

// Keep this stored across all projects, only display this once per month
const AI_DATA_PROCESSING_DISMISSED_STORAGE_KEY = `posthog_ai_data_processing_dismissed_${dayjs().format('YYYY-MM')}`

// Records, per organization, that this member has already asked an admin to enable
// PostHog AI — so the request button doesn't invite repeated submissions.
const AI_ACCESS_REQUESTED_STORAGE_KEY = 'posthog_ai_access_requested_by_org'

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
        ],
        actions: [router, ['locationChanged'], sidePanelStateLogic, ['openSidePanel']],
    })),
    actions({
        openSidePanelMax: (conversationId?: string) => ({ conversationId }),
        openSidePanelMaxWithTaskBind: (taskId: string) => ({ taskId }),
        askSidePanelMax: (prompt: string) => ({ prompt }),
        acceptDataProcessing: (testOnlyOverride?: boolean) => ({ testOnlyOverride }),
        registerTool: (tool: ToolRegistration) => ({ tool }),
        deregisterTool: (key: string) => ({ key }),
        prependOrReplaceConversation: (conversation: ConversationDetail | Conversation) => ({ conversation }),
        deleteConversation: (id: string) => ({ id }),
        dismissLiabilityNotice: true,
        dismissDataProcessing: true,
        requestAiAccess: true,
        markAiAccessRequested: (organizationId: string) => ({ organizationId }),
        requestAiAccessError: true,
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
        requestingAiAccess: [
            false,
            {
                requestAiAccess: () => true,
                markAiAccessRequested: () => false,
                requestAiAccessError: () => false,
            },
        ],
        aiAccessRequestedByOrg: [
            {} as Record<string, boolean>,
            { persist: true, storageKey: AI_ACCESS_REQUESTED_STORAGE_KEY },
            {
                markAiAccessRequested: (state, { organizationId }) => ({ ...state, [organizationId]: true }),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        acceptDataProcessing: async ({ testOnlyOverride }) => {
            await organizationLogic.asyncActions.updateOrganization({
                is_ai_data_processing_approved: testOnlyOverride ?? true,
            })
        },
        requestAiAccess: async () => {
            const organization = values.currentOrganization
            if (!organization) {
                actions.requestAiAccessError()
                return
            }
            try {
                // Backend notifies the org admins/owners via a customer.io email — keeps the
                // recipient resolution server-side so it can't be tampered with from the client.
                await requestAiAccessCreate(organization.id)
                actions.markAiAccessRequested(organization.id)
                lemonToast.success('Request sent to your organization admins')
            } catch {
                actions.requestAiAccessError()
                lemonToast.error('Could not send your request. Please try again.')
            }
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
        // Open the side panel on a fresh chat bound to a sandbox Task (inbox "Open task" — in-place,
        // not a new tab). The side panel doesn't sync the URL, so the binding is seeded directly here
        // rather than via the `bind_task` param the scene route reads. `setPendingBindTaskId` runs
        // after `startNewConversation`, which clears it.
        openSidePanelMaxWithTaskBind: ({ taskId }) => {
            if (!values.sidePanelOpen || values.selectedTab !== SidePanelTab.Max) {
                actions.openSidePanel(SidePanelTab.Max)
            }
            let logic = maxLogic.findMounted({ panelId: SIDE_PANEL_PANEL_ID })
            if (!logic) {
                logic = maxLogic({ panelId: SIDE_PANEL_PANEL_ID })
                logic.mount() // we're never unmounting this
            }
            logic.actions.startNewConversation()
            logic.actions.setPendingBindTaskId(taskId)
        },
        loadConversationHistoryFailure: ({ errorObject }) => {
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
    afterMount(({ actions }) => {
        actions.loadConversationHistory()
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
        aiAccessRequested: [
            (s) => [s.aiAccessRequestedByOrg, s.currentOrganization],
            (aiAccessRequestedByOrg, currentOrganization): boolean =>
                !!(currentOrganization && aiAccessRequestedByOrg[currentOrganization.id]),
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
