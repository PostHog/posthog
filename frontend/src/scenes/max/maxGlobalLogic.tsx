import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import type { maxGlobalLogicType } from './maxGlobalLogicType'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'
import { AssistantContextualTool, AssistantNavigateUrls } from '~/queries/schema/schema-assistant-messages'
import { routes } from 'scenes/scenes'
import { IconCompass } from '@posthog/icons'
import { Scene } from 'scenes/sceneTypes'
import { SidePanelTab } from '~/types'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export interface ToolDefinition {
    /** A unique identifier for the tool */
    name: AssistantContextualTool
    /** A user-friendly display name for the tool */
    displayName: string
    /** A user-friendly description for the tool */
    description: `Max can ${string}`
    /**
     * Optional specific @posthog/icons icon
     * @default <IconWrench />
     */
    icon?: React.ReactNode
    /** Contextual data to be included for use by the LLM */
    context: Record<string, any>
    /**
     * Optional: If this tool is the main one of the page, you can override Max's default intro headline and description when it's mounted.
     *
     * Note that if more than one mounted tool has an intro override, only one will take effect.
     */
    introOverride?: {
        /** The default is something like "How can I help you build?" - stick true to this question form. */
        headline: string
        /** The default is "Ask me about your product and your users." */
        description: string
    }
    /** Optional: When in context, the tool can add items to the pool of Max's suggested questions */
    suggestions?: string[] // TODO: Suggestions aren't used yet, pending a refactor of maxLogic's allSuggestions
    /** The callback function that will be executed with the LLM's tool call output */
    callback: (toolOutput: any) => void | Promise<void>
}

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
        registerTool: (tool: ToolDefinition) => ({ tool }),
        deregisterTool: (key: string) => ({ key }),
        setIsFloatingMaxExpanded: (isExpanded: boolean) => ({ isExpanded }),
        setFloatingMaxPosition: (position: { x: number; y: number; side: 'left' | 'right' }) => ({ position }),
        setShowFloatingMaxSuggestions: (value: boolean) => ({ value }),
        setFloatingMaxDragState: (dragState: { isDragging: boolean; isAnimating: boolean }) => ({ dragState }),
    }),
    reducers({
        toolMap: [
            {
                // The navigation tool is available everywhere
                navigate: {
                    name: 'navigate' as const,
                    displayName: 'Navigate',
                    description: 'Max can navigate to other places in PostHog',
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
            } as Record<string, ToolDefinition>,
            {
                registerTool: (state, { tool }) => ({
                    ...state,
                    [tool.name]: tool,
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
        tools: [(s) => [s.toolMap], (toolMap): ToolDefinition[] => Object.values(toolMap)],
    }),
])
