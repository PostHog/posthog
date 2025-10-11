import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { IconBook, IconCompass, IconDashboard, IconGraph, IconRewindPlay } from '@posthog/icons'

import { OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { routes } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SidePanelTab } from '~/types'

import { TOOL_DEFINITIONS, ToolRegistration } from './max-constants'
import type { maxGlobalLogicType } from './maxGlobalLogicType'
import { maxLogic } from './maxLogic'
import { buildSceneDescriptionsContext } from './utils/sceneDescriptionsContext'

/** Tools available everywhere. These CAN be shadowed by contextual tools for scene-specific handling (e.g. to intercept insight creation). */
export const STATIC_TOOLS: ToolRegistration[] = [
    {
        identifier: 'navigate' as const,
        name: TOOL_DEFINITIONS['navigate'].name,
        description: TOOL_DEFINITIONS['navigate'].description,
        icon: <IconCompass />,
        context: { current_page: location.pathname, scene_descriptions: buildSceneDescriptionsContext() },
        callback: async (toolOutput) => {
            const { page_key: pageKey } = toolOutput
            if (!(pageKey in urls)) {
                throw new Error(`${pageKey} not in urls`)
            }
            // @ts-expect-error - we can ignore the error about expecting more than 0 args
            const url = urls[pageKey as keyof typeof urls]()
            // Include the conversation ID and panel to ensure the side panel is open
            // (esp. when the navigate tool is used from the full-page Max)
            router.actions.push(url, { chat: maxLogic.values.frontendConversationId }, { panel: SidePanelTab.Max })
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
        icon: <IconDashboard />,
    },
    {
        identifier: 'search_docs' as const,
        name: TOOL_DEFINITIONS['search_docs'].name,
        description: TOOL_DEFINITIONS['search_docs'].description,
        icon: <IconBook />,
    },
    {
        identifier: 'session_summarization' as const,
        name: TOOL_DEFINITIONS['session_summarization'].name,
        description: TOOL_DEFINITIONS['session_summarization'].description,
        icon: <IconRewindPlay />,
    },
    {
        identifier: 'create_and_query_insight' as const,
        name: 'Query data',
        description: 'Query data by creating insights and SQL queries',
        icon: <IconGraph />,
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
        ],
        actions: [router, ['locationChanged']],
    })),
    actions({
        acceptDataProcessing: (testOnlyOverride?: boolean) => ({ testOnlyOverride }),
        registerTool: (tool: ToolRegistration) => ({ tool }),
        deregisterTool: (key: string) => ({ key }),
    }),
    reducers({
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
            // Update navigation tool with the current page
            actions.registerTool({
                ...values.toolMap.navigate,
                context: { current_page: pathname, scene_descriptions: buildSceneDescriptionsContext() },
            })
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
            (registeredToolMap, availableStaticTools) => ({
                ...Object.fromEntries(availableStaticTools.map((tool) => [tool.identifier, tool])),
                ...registeredToolMap,
            }),
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
