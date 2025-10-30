import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { routes } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { Conversation, ConversationDetail, SidePanelTab } from '~/types'

import { TOOL_DEFINITIONS, ToolRegistration } from './max-constants'
import type { maxGlobalLogicType } from './maxGlobalLogicType'
import { maxLogic, mergeConversationHistory } from './maxLogic'
import { buildSceneDescriptionsContext } from './utils/sceneDescriptionsContext'

/** Tools available everywhere. These CAN be shadowed by contextual tools for scene-specific handling (e.g. to intercept insight creation). */
export const STATIC_TOOLS: ToolRegistration[] = [
    {
        identifier: 'web_search',
        name: TOOL_DEFINITIONS['web_search'].name,
        description: TOOL_DEFINITIONS['web_search'].description,
    },
    {
        identifier: 'navigate' as const,
        name: TOOL_DEFINITIONS['navigate'].name,
        description: TOOL_DEFINITIONS['navigate'].description,
        context: { current_page: location.pathname, scene_descriptions: buildSceneDescriptionsContext() },
        callback: async (toolOutput, conversationId) => {
            const { page_key: pageKey } = toolOutput
            if (!(pageKey in urls)) {
                throw new Error(`${pageKey} not in urls`)
            }
            // @ts-expect-error - we can ignore the error about expecting more than 0 args
            const url = urls[pageKey as keyof typeof urls]()
            // Include the conversation ID and panel to ensure the side panel is open
            // (esp. when the navigate tool is used from the full-page Max)

            maxGlobalLogic.findMounted()?.actions.openSidePanelMax(conversationId)
            router.actions.push(url)

            // First wait for navigation to complete
            await new Promise<void>((resolve, reject) => {
                const NAVIGATION_TIMEOUT = 1000 // 1 second timeout
                const startTime = performance.now()
                const checkPathname = (): void => {
                    if (sceneLogic.values.activeSceneId === routes[url]?.[0]) {
                        resolve()
                    } else if (performance.now() - startTime > NAVIGATION_TIMEOUT) {
                        reject(new Error('Navigation timeout'))
                    } else {
                        setTimeout(checkPathname, 50)
                    }
                }
                checkPathname()
            })
        },
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
        identifier: 'session_summarization' as const,
        name: TOOL_DEFINITIONS['session_summarization'].name,
        description: TOOL_DEFINITIONS['session_summarization'].description,
    },
    {
        identifier: 'create_and_query_insight' as const,
        name: TOOL_DEFINITIONS['create_and_query_insight'].name,
        description: TOOL_DEFINITIONS['create_and_query_insight'].description,
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

    loaders({
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
            },
        ],
    }),

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
        locationChanged: ({ pathname }) => {
            if (
                values.registeredToolMap.navigate &&
                pathname === values.registeredToolMap.navigate.context?.current_page
            ) {
                return // No change to path
            }
            // Update navigation tool with the current page
            actions.registerTool({
                ...values.toolMap.navigate,
                context: { current_page: pathname, scene_descriptions: buildSceneDescriptionsContext() },
            })
        },
        askSidePanelMax: ({ prompt }) => {
            let logic = maxLogic.findMounted({ tabId: 'sidepanel' })
            if (!logic) {
                logic = maxLogic({ tabId: 'sidepanel' })
                logic.mount() // we're never unmounting this
            }
            actions.openSidePanelMax()
            logic.actions.askMax(prompt)
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
            (featureFlags): ToolRegistration[] =>
                STATIC_TOOLS.filter((tool) => {
                    // Only register the static tools that either aren't flagged or have their flag enabled
                    const toolDefinition = TOOL_DEFINITIONS[tool.identifier]
                    return !toolDefinition.flag || featureFlags[toolDefinition.flag]
                }),
        ],
        toolMap: [
            (s) => [s.registeredToolMap, s.availableStaticTools],
            (registeredToolMap, availableStaticTools) => {
                if (registeredToolMap.edit_current_insight) {
                    availableStaticTools = availableStaticTools.filter(
                        (tool) => tool.identifier !== 'create_and_query_insight'
                    )
                }
                return {
                    ...Object.fromEntries(availableStaticTools.map((tool) => [tool.identifier, tool])),
                    ...registeredToolMap,
                }
            },
        ],
        tools: [(s) => [s.toolMap], (toolMap): ToolRegistration[] => Object.values(toolMap)],
        editInsightToolRegistered: [
            (s) => [s.registeredToolMap],
            (registeredToolMap) => !!registeredToolMap.create_and_query_insight,
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
