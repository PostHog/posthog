import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic as globalTeamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { ActivationTaskStatus } from '~/types'

import type { globalSetupLogicType } from './globalSetupLogicType'
import { PRODUCTS_WITH_SETUP } from './productSetupRegistry'
import { SetupTaskId } from './types'

/** URL search param that triggers opening the quick start popover */
export const QUICK_START_PARAM = 'quickstart'

/**
 * Global setup logic - the single source of truth for task completion and UI state.
 *
 * This logic handles:
 * 1. Task completion/skipping (called from anywhere via findMounted())
 * 2. UI state for the global setup popover (selectedProduct, isGlobalModalOpen)
 *
 * External logics should call globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(taskId)
 * to mark tasks as complete. This updates team.onboarding_tasks and tracks analytics.
 */
export const globalSetupLogic = kea<globalSetupLogicType>([
    path(['lib', 'components', 'ProductSetup', 'globalSetupLogic']),
    connect({
        values: [sceneLogic, ['activeSceneProductKey']],
    }),
    actions({
        // Task actions - single source of truth for task state updates
        // All actions accept either a single task ID or an array of task IDs
        markTaskAsCompleted: (taskIdOrIds: SetupTaskId | SetupTaskId[]) => ({ taskIdOrIds }),
        markTaskAsSkipped: (taskIdOrIds: SetupTaskId | SetupTaskId[]) => ({ taskIdOrIds }),
        unmarkTaskAsCompleted: (taskIdOrIds: SetupTaskId | SetupTaskId[]) => ({ taskIdOrIds }),
        unmarkTaskAsSkipped: (taskIdOrIds: SetupTaskId | SetupTaskId[]) => ({ taskIdOrIds }),

        // Internal actions for optimistic updates
        // null value means "this task should appear as unmarked"
        setOptimisticTaskStatuses: (statuses: Record<string, ActivationTaskStatus | null>) => ({ statuses }),
        clearOptimisticTaskStatuses: (taskIds: SetupTaskId[]) => ({ taskIds }),

        // UI actions for the global setup popover
        setSelectedProduct: (productKey: ProductKey) => ({ productKey }),
        openGlobalSetup: true,
        closeGlobalSetup: true,

        // Element highlighting after navigation
        setHighlightSelector: (selector: string | null) => ({ selector }),
        clearHighlightSelector: true,
    }),
    reducers({
        // Currently selected product in the global setup popover
        selectedProduct: [
            ProductKey.PRODUCT_ANALYTICS as ProductKey,
            {
                setSelectedProduct: (_, { productKey }) => productKey,
            },
        ],
        // Whether the global setup popover is open
        isGlobalModalOpen: [
            false,
            {
                openGlobalSetup: () => true,
                closeGlobalSetup: () => false,
            },
        ],
        // Selector for element to highlight after navigation
        highlightSelector: [
            null as string | null,
            {
                setHighlightSelector: (_, { selector }) => selector,
                clearHighlightSelector: () => null,
            },
        ],
        // Optimistic task statuses - updated immediately before API call completes
        // This allows the UI to respond instantly to user actions
        // null means "this task should appear as unmarked" (for undo operations)
        optimisticTaskStatuses: [
            {} as Record<string, ActivationTaskStatus | null>,
            {
                setOptimisticTaskStatuses: (state, { statuses }) => ({ ...state, ...statuses }),
                clearOptimisticTaskStatuses: (state, { taskIds }) => {
                    const newState = { ...state }
                    for (const taskId of taskIds) {
                        // Set to null instead of deleting - null means "unmarked"
                        newState[taskId] = null
                    }
                    return newState
                },
            },
        ],
    }),
    selectors({
        availableProducts: [() => [], () => PRODUCTS_WITH_SETUP],
        // The product key from the current scene - filtered to only include products with setup
        // Used for auto-selecting the product in the popover
        sceneProductKey: [
            (s) => [s.activeSceneProductKey],
            (activeSceneProductKey): ProductKey | null => {
                if (activeSceneProductKey && PRODUCTS_WITH_SETUP.includes(activeSceneProductKey)) {
                    return activeSceneProductKey
                }
                return null
            },
        ],
        // Whether the current scene has a product key that doesn't have setup configured
        // Used to hide the Quick Start button on scenes for products without onboarding
        sceneHasNoSetup: [
            (s) => [s.activeSceneProductKey],
            (activeSceneProductKey): boolean => {
                return activeSceneProductKey !== null && !PRODUCTS_WITH_SETUP.includes(activeSceneProductKey)
            },
        ],
        // Whether the product selection is locked to the current scene
        isProductSelectionLocked: [(s) => [s.sceneProductKey], (sceneProductKey) => sceneProductKey !== null],
    }),
    // NOTE: Not using `connect` here because the teamLogic might not have mounted yet
    // by the time this logic is mounted
    listeners(({ actions }) => ({
        markTaskAsCompleted: async ({ taskIdOrIds }) => {
            const taskIds = Array.isArray(taskIdOrIds) ? taskIdOrIds : [taskIdOrIds]

            const teamLogic = globalTeamLogic.findMounted()
            if (!teamLogic) {
                return
            }

            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam || !('onboarding_tasks' in currentTeam)) {
                return
            }

            // If all tasks already completed, don't do anything
            if (taskIds.every((taskId) => currentTeam.onboarding_tasks?.[taskId] === ActivationTaskStatus.COMPLETED)) {
                return
            }

            // Optimistically update UI immediately
            const optimisticStatuses: Record<string, ActivationTaskStatus> = {}
            for (const taskId of taskIds) {
                optimisticStatuses[taskId] = ActivationTaskStatus.COMPLETED
            }
            actions.setOptimisticTaskStatuses(optimisticStatuses)

            // Reopen the quick start popover to show progress immediately
            actions.openGlobalSetup()

            // Track analytics for each task
            for (const taskId of taskIds) {
                posthog.capture('product setup task completed', { task: taskId })
            }

            // Persist to server in the background
            const onboardingTasks = { ...currentTeam.onboarding_tasks, ...optimisticStatuses }
            teamLogic.actions.updateCurrentTeam({ onboarding_tasks: onboardingTasks })
        },

        markTaskAsSkipped: async ({ taskIdOrIds }) => {
            const taskIds = Array.isArray(taskIdOrIds) ? taskIdOrIds : [taskIdOrIds]

            const teamLogic = globalTeamLogic.findMounted()
            if (!teamLogic) {
                return
            }

            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam || !('onboarding_tasks' in currentTeam)) {
                return
            }

            // If all tasks already skipped, don't do anything
            if (taskIds.every((taskId) => currentTeam.onboarding_tasks?.[taskId] === ActivationTaskStatus.SKIPPED)) {
                return
            }

            // Optimistically update UI immediately
            const optimisticStatuses: Record<string, ActivationTaskStatus> = {}
            for (const taskId of taskIds) {
                optimisticStatuses[taskId] = ActivationTaskStatus.SKIPPED
            }
            actions.setOptimisticTaskStatuses(optimisticStatuses)

            // Track analytics for each task
            for (const taskId of taskIds) {
                posthog.capture('product setup task skipped', { task: taskId })
            }

            const onboardingTasks = { ...currentTeam.onboarding_tasks, ...optimisticStatuses }
            teamLogic.actions.updateCurrentTeam({ onboarding_tasks: onboardingTasks })
        },

        unmarkTaskAsCompleted: async ({ taskIdOrIds }) => {
            const taskIds = Array.isArray(taskIdOrIds) ? taskIdOrIds : [taskIdOrIds]

            // Clear optimistic statuses immediately for instant UI feedback
            actions.clearOptimisticTaskStatuses(taskIds)

            // Track analytics for each task
            for (const taskId of taskIds) {
                posthog.capture('product setup task uncompleted', { task: taskId })
            }

            // Persist to server in the background
            const teamLogic = globalTeamLogic.findMounted()
            if (!teamLogic) {
                return
            }

            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam || !('onboarding_tasks' in currentTeam)) {
                return
            }

            const onboardingTasks = { ...currentTeam.onboarding_tasks }
            for (const taskId of taskIds) {
                delete onboardingTasks[taskId]
            }

            teamLogic.actions.updateCurrentTeam({ onboarding_tasks: onboardingTasks })
        },

        unmarkTaskAsSkipped: async ({ taskIdOrIds }) => {
            const taskIds = Array.isArray(taskIdOrIds) ? taskIdOrIds : [taskIdOrIds]

            // Clear optimistic statuses immediately for instant UI feedback
            actions.clearOptimisticTaskStatuses(taskIds)

            // Track analytics for each task
            for (const taskId of taskIds) {
                posthog.capture('product setup task unskipped', { task: taskId })
            }

            // Persist to server in the background
            const teamLogic = globalTeamLogic.findMounted()
            if (!teamLogic) {
                return
            }

            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam || !('onboarding_tasks' in currentTeam)) {
                return
            }

            const onboardingTasks = { ...currentTeam.onboarding_tasks }
            for (const taskId of taskIds) {
                delete onboardingTasks[taskId]
            }

            teamLogic.actions.updateCurrentTeam({ onboarding_tasks: onboardingTasks })
        },
    })),
    subscriptions(({ actions, values }) => ({
        // When the scene product key changes, auto-select it in the popover
        sceneProductKey: (sceneProductKey: ProductKey | null) => {
            if (sceneProductKey && sceneProductKey !== values.selectedProduct) {
                actions.setSelectedProduct(sceneProductKey)
            }
        },
    })),
    afterMount(({ actions }) => {
        // Check if URL has quickstart param set to 'true' - if so, open the popover and remove the param
        const searchParams = new URLSearchParams(window.location.search)
        const quickstartValue = searchParams.get(QUICK_START_PARAM)

        if (quickstartValue === 'true') {
            actions.openGlobalSetup()

            // Remove the param from URL without triggering navigation
            searchParams.delete(QUICK_START_PARAM)
            const newSearch = searchParams.toString()
            const newUrl = window.location.pathname + (newSearch ? `?${newSearch}` : '') + window.location.hash
            window.history.replaceState({}, '', newUrl)
        }
    }),
])
