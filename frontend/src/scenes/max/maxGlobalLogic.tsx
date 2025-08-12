import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import type { maxGlobalLogicType } from './maxGlobalLogicType'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'
import { AssistantNavigateUrls } from '~/queries/schema/schema-assistant-messages'
import { routes } from 'scenes/scenes'
import { IconBook, IconCompass, IconEye } from '@posthog/icons'
import { Scene } from 'scenes/sceneTypes'
import { SidePanelTab } from '~/types'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { TOOL_DEFINITIONS, ToolRegistration } from './max-constants'

/** Tools available everywhere. These CAN be shadowed by contextual tools for scene-specific handling (e.g. to intercept insight creation). */
export const STATIC_TOOLS: ToolRegistration[] = [
    {
        identifier: 'navigate' as const,
        name: TOOL_DEFINITIONS['navigate'].name,
        description: TOOL_DEFINITIONS['navigate'].description,
        icon: <IconCompass />,
        context: { current_page: location.pathname },
        callback: async (toolOutput) => {
            const { page_key: pageKey } = toolOutput
            if (!(pageKey in urls)) {
                throw new Error(`${pageKey} not in urls`)
            }
            const url = urls[pageKey as AssistantNavigateUrls]()
            router.actions.push(url)
            // First wait for navigation to complete
            await new Promise<void>((resolve, reject) => {
                const NAVIGATION_TIMEOUT = 1000 // 1 second timeout
                const startTime = performance.now()
                const checkPathname = (): void => {
                    if (sceneLogic.values.activeScene === routes[url]?.[0]) {
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
        identifier: 'search_docs' as const,
        name: TOOL_DEFINITIONS['search_docs'].name,
        description: TOOL_DEFINITIONS['search_docs'].description,
        icon: <IconBook />,
    },
    {
        identifier: 'create_and_query_insight' as const,
        name: 'Query data',
        description: 'Query data by creating insights and SQL queries',
        icon: <IconEye />,
    },
]

export const maxGlobalLogic = kea<maxGlobalLogicType>([
    path(['scenes', 'max', 'maxGlobalLogic']),
    connect(() => ({
        values: [
            organizationLogic,
            ['currentOrganization'],
            sceneLogic,
            ['scene', 'sceneConfig'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [router, ['locationChanged']],
    })),
    actions({
        acceptDataProcessing: (testOnlyOverride?: boolean) => ({ testOnlyOverride }),
        registerTool: (tool: ToolRegistration) => ({ tool }),
        deregisterTool: (key: string) => ({ key }),
        setIsFloatingMaxExpanded: (isExpanded: boolean) => ({ isExpanded }),
        setFloatingMaxPosition: (position: { x: number; y: number; side: 'left' | 'right' }) => ({ position }),
        setShowFloatingMaxSuggestions: (value: boolean) => ({ value }),
        setFloatingMaxDragState: (dragState: { isDragging: boolean; isAnimating: boolean }) => ({ dragState }),
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
        isFloatingMaxExpanded: [
            true,
            {
                persist: true,
            },
            {
                setIsFloatingMaxExpanded: (_, { isExpanded }) => isExpanded,
            },
        ],
        floatingMaxPosition: [
            null as { x: number; y: number; side: 'left' | 'right' } | null,
            {
                persist: true,
            },
            {
                setFloatingMaxPosition: (_, { position }) => position,
            },
        ],
        showFloatingMaxSuggestions: [
            false,
            {
                setShowFloatingMaxSuggestions: (_, { value }) => value,
            },
        ],
        floatingMaxDragState: [
            { isDragging: false, isAnimating: false } as { isDragging: boolean; isAnimating: boolean },
            {
                setFloatingMaxDragState: (_, { dragState }) => dragState,
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
                context: { current_page: pathname },
            })
        },
    })),
    selectors({
        showFloatingMax: [
            (s) => [
                s.scene,
                s.sceneConfig,
                s.isFloatingMaxExpanded,
                sidePanelLogic.selectors.sidePanelOpen,
                sidePanelLogic.selectors.selectedTab,
                s.featureFlags,
            ],
            (scene, sceneConfig, isFloatingMaxExpanded, sidePanelOpen, selectedTab, featureFlags) =>
                sceneConfig &&
                !sceneConfig.onlyUnauthenticated &&
                sceneConfig.layout !== 'plain' &&
                !(scene === Scene.Max && !isFloatingMaxExpanded) && // In the full Max scene, and Max is not intentionally in floating mode (i.e. expanded)
                !(sidePanelOpen && selectedTab === SidePanelTab.Max) && // The Max side panel is open
                featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG] &&
                featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG],
        ],
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
        toolMap: [
            (s) => [s.registeredToolMap],
            (registeredToolMap) => ({
                ...Object.fromEntries(STATIC_TOOLS.map((tool) => [tool.identifier, tool])),
                ...registeredToolMap,
            }),
        ],
        tools: [(s) => [s.toolMap], (toolMap): ToolRegistration[] => Object.values(toolMap)],
    }),
])
