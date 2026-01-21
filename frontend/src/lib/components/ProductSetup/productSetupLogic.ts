import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { reverseProxyCheckerLogic } from 'lib/components/ReverseProxyChecker/reverseProxyCheckerLogic'
import { hasRecentAIEvents } from 'lib/utils/aiEventsUtils'
import { organizationLogic } from 'scenes/organizationLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivationTaskStatus, EventDefinitionType } from '~/types'

import { globalSetupLogic } from './globalSetupLogic'
import type { productSetupLogicType } from './productSetupLogicType'
import { getProductSetupConfig, getTasksForProduct } from './productSetupRegistry'
import { SetupTaskId, type SetupTaskWithState } from './types'

export interface ProductSetupLogicProps {
    productKey: ProductKey
}

const DISMISSED_STORAGE_KEY = 'posthog_product_setup_dismissed'

/**
 * Product setup logic - handles product-specific state and UI for the setup experience.
 *
 * This logic is keyed by productKey and handles:
 * 1. Reading task state (selectors derive from team.onboarding_tasks)
 * 2. Running task actions (navigation, opening modals, etc.)
 * 3. Product-specific UI state (expandedTaskId, isDismissed, isModalOpen)
 * 4. Product-specific loaders (customEventsCount, hasSentAIEvent)
 *
 * Task completion is handled by globalSetupLogic - this logic just reads and displays state.
 */
export const productSetupLogic = kea<productSetupLogicType>([
    path((key) => ['lib', 'components', 'ProductSetup', 'productSetupLogic', key]),
    props({} as ProductSetupLogicProps),
    key((props) => props.productKey),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam'],
            reverseProxyCheckerLogic,
            ['hasReverseProxy'],
            organizationLogic,
            ['isCurrentOrganizationNew'],
        ],
        actions: [
            inviteLogic,
            ['showInviteModal'],
            sidePanelSettingsLogic,
            ['openSettingsPanel'],
            reverseProxyCheckerLogic,
            ['loadHasReverseProxy'],
            globalSetupLogic,
            [
                'openGlobalSetup',
                'closeGlobalSetup',
                'markTaskAsCompleted',
                'unmarkTaskAsCompleted',
                'markTaskAsSkipped',
                'unmarkTaskAsSkipped',
                'setHighlightSelector',
            ],
        ],
    })),
    actions({
        // Task execution action
        runTask: (taskId: SetupTaskId) => ({ taskId }),

        // UI actions
        setExpandedTaskId: (taskId: SetupTaskId | null) => ({ taskId }),
        openSetupModal: true,
        closeSetupModal: true,
        dismissSetup: true,
        undismissSetup: true,
        setShowCelebration: (show: boolean) => ({ show }),

        // Data loading triggers
        loadCompletionData: true,
    }),
    reducers(({ props }) => ({
        isModalOpen: [
            false,
            {
                openSetupModal: () => true,
                closeSetupModal: () => false,
            },
        ],
        expandedTaskId: [
            null as SetupTaskId | null,
            {
                setExpandedTaskId: (_, { taskId }) => taskId,
            },
        ],
        isDismissed: [
            false,
            { persist: true, prefix: `${DISMISSED_STORAGE_KEY}_${props.productKey}` },
            {
                dismissSetup: () => true,
                undismissSetup: () => false,
            },
        ],
        showCelebration: [
            false,
            {
                setShowCelebration: (_, { show }) => show,
            },
        ],
    })),
    loaders(({ cache }) => ({
        customEventsCount: [
            0,
            {
                loadCustomEvents: async (_, breakpoint) => {
                    await breakpoint(200)
                    const url = api.eventDefinitions.determineListEndpoint({
                        event_type: EventDefinitionType.EventCustom,
                    })
                    if (url in (cache.apiCache ?? {})) {
                        return cache.apiCache[url]
                    }
                    const response = await api.get(url)
                    breakpoint()
                    cache.apiCache = {
                        ...cache.apiCache,
                        [url]: response.count,
                    }
                    return cache.apiCache[url]
                },
            },
        ],
        hasSentAIEvent: {
            __default: undefined as boolean | undefined,
            loadAIEventDefinitions: async (): Promise<boolean> => {
                return hasRecentAIEvents()
            },
        },
    })),
    selectors({
        productConfig: [(_, p) => [p.productKey], (productKey) => getProductSetupConfig(productKey)],
        allTasks: [(_, p) => [p.productKey], (productKey) => getTasksForProduct(productKey)],
        savedOnboardingTasks: [
            (s) => [s.currentTeam],
            (currentTeam) => currentTeam?.onboarding_tasks ?? ({} as Record<string, ActivationTaskStatus>),
        ],
        tasksWithState: [
            (s) => [s.allTasks, s.savedOnboardingTasks, s.hasReverseProxy],
            (allTasks, savedOnboardingTasks, hasReverseProxy): SetupTaskWithState[] => {
                return allTasks.map((task) => {
                    // Check for auto-completion conditions
                    let isAutoCompleted = false

                    // Reverse proxy task auto-completes if proxy is detected
                    if (task.id === SetupTaskId.SetUpReverseProxy && hasReverseProxy) {
                        isAutoCompleted = true
                    }

                    const completed =
                        isAutoCompleted || savedOnboardingTasks[task.id] === ActivationTaskStatus.COMPLETED
                    const skipped = savedOnboardingTasks[task.id] === ActivationTaskStatus.SKIPPED

                    // Check dependencies
                    let lockedReason: string | undefined
                    if (task.dependsOn) {
                        for (const depId of task.dependsOn) {
                            if (savedOnboardingTasks[depId] !== ActivationTaskStatus.COMPLETED) {
                                const depTask = allTasks.find((t) => t.id === depId)
                                lockedReason = depTask
                                    ? `Complete "${depTask.title}" first`
                                    : 'Complete dependencies first'
                                break
                            }
                        }
                    }

                    return {
                        ...task,
                        completed,
                        skipped,
                        lockedReason,
                    }
                })
            },
        ],
        activeTasks: [(s) => [s.tasksWithState], (tasks) => tasks.filter((task) => !task.completed && !task.skipped)],
        completedTasks: [(s) => [s.tasksWithState], (tasks) => tasks.filter((task) => task.completed)],
        skippedTasks: [(s) => [s.tasksWithState], (tasks) => tasks.filter((task) => task.skipped)],
        totalTasks: [(s) => [s.tasksWithState], (tasks) => tasks.length],
        completedCount: [
            (s) => [s.completedTasks, s.skippedTasks],
            (completed: SetupTaskWithState[], skipped: SetupTaskWithState[]) => completed.length + skipped.length,
        ],
        remainingCount: [(s) => [s.activeTasks], (tasks) => tasks.length],
        completionPercent: [
            (s) => [s.completedCount, s.totalTasks],
            (completed, total) => {
                if (total === 0) {
                    return 100
                }
                const percent = Math.round((completed / total) * 100)
                return percent >= 5 ? percent : 5 // Min 5% for visibility
            },
        ],
        isSetupComplete: [(s) => [s.remainingCount], (remaining) => remaining === 0],
        shouldShowSetup: [
            (s) => [s.isSetupComplete, s.productConfig, s.isCurrentOrganizationNew],
            (isComplete, config, isNewOrg) => {
                // Don't show if no valid config
                if (!config || !config.title) {
                    return false
                }
                // Don't show for organizations older than 3 months
                if (!isNewOrg) {
                    return false
                }
                // Don't show if all tasks are complete
                return !isComplete
            },
        ],
        firstAvailableTask: [(s) => [s.activeTasks], (tasks) => tasks.find((t) => !t.lockedReason) ?? null],
    }),
    listeners(({ props, actions, values }) => ({
        runTask: ({ taskId }) => {
            const task = values.tasksWithState.find((t) => t.id === taskId)
            if (!task) {
                return
            }

            // Special cases that need non-navigation actions
            switch (taskId) {
                case 'setup_session_recordings':
                    // Open settings panel in addition to navigation
                    actions.openSettingsPanel({ sectionId: 'project-replay' })
                    break
            }

            // Use task's getUrl if available, otherwise fall back to docsUrl
            if (task.getUrl) {
                // Close modal before internal navigation (keeps the full "Quick start" button visible)
                actions.closeGlobalSetup()

                // Set highlight selector before navigation so it can highlight after page loads
                if (task.targetSelector) {
                    actions.setHighlightSelector(task.targetSelector)
                }
                router.actions.push(task.getUrl())
            } else if (task.docsUrl) {
                // Keep modal open for external docs links
                window.open(task.docsUrl, '_blank')
            }
        },
        dismissSetup: () => {
            posthog.capture('product setup dismissed', {
                product: props.productKey,
                completed_count: values.completedCount,
                total_count: values.totalTasks,
            })
        },
        loadCompletionData: () => {
            // Load reverse proxy status
            if (!values.currentTeam?.onboarding_tasks?.[SetupTaskId.SetUpReverseProxy]) {
                actions.loadHasReverseProxy()
            }

            // Load custom events for Product Analytics
            if (props.productKey === ProductKey.PRODUCT_ANALYTICS) {
                actions.loadCustomEvents({})
            }

            // Load AI events for LLM Analytics
            if (props.productKey === ProductKey.LLM_ANALYTICS) {
                actions.loadAIEventDefinitions()
            }
        },
        loadCustomEventsSuccess: () => {
            if (values.customEventsCount > 0) {
                // Use globalSetupLogic for task completion
                actions.markTaskAsCompleted(SetupTaskId.TrackCustomEvents)
            }
        },
        loadAIEventDefinitionsSuccess: () => {
            if (values.hasSentAIEvent) {
                // Use globalSetupLogic for task completion
                actions.markTaskAsCompleted(SetupTaskId.IngestFirstLlmEvent)
            }
        },
        openSetupModal: () => {
            actions.loadCompletionData()

            // Auto-expand first available task
            if (!values.expandedTaskId && values.firstAvailableTask) {
                actions.setExpandedTaskId(values.firstAvailableTask.id)
            }

            posthog.capture('product setup modal opened', {
                product: props.productKey,
                remaining_tasks: values.remainingCount,
            })
        },
    })),
])
