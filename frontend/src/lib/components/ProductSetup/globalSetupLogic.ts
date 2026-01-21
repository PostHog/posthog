import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { teamLogic as globalTeamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { ActivationTaskStatus } from '~/types'

import type { globalSetupLogicType } from './globalSetupLogicType'
import { PRODUCTS_WITH_SETUP } from './productSetupRegistry'
import { SetupTaskId } from './types'

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
    actions({
        // Task actions - single source of truth for task state updates
        markTaskAsCompleted: (taskId: SetupTaskId) => ({ taskId }),
        markTaskAsSkipped: (taskIdOrIds: SetupTaskId | SetupTaskId[]) => ({ taskIdOrIds }),
        unmarkTaskAsCompleted: (taskId: SetupTaskId) => ({ taskId }),
        unmarkTaskAsSkipped: (taskId: SetupTaskId) => ({ taskId }),

        // UI actions for the global setup popover
        setSelectedProduct: (productKey: ProductKey) => ({ productKey }),
        openGlobalSetup: true,
        closeGlobalSetup: true,

        // Scene-specific product key - when set, locks the popover to this product
        setSceneProductKey: (productKey: ProductKey | null) => ({ productKey }),

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
                // When scene product key is set, also update selected product
                setSceneProductKey: (state, { productKey }) => productKey ?? state,
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
        // The product key from the current scene - when set, locks product selection
        sceneProductKey: [
            null as ProductKey | null,
            {
                setSceneProductKey: (_, { productKey }) => productKey,
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
    }),
    selectors({
        availableProducts: [() => [], () => PRODUCTS_WITH_SETUP],
        // Whether the product selection is locked to the current scene
        isProductSelectionLocked: [(s) => [s.sceneProductKey], (sceneProductKey) => sceneProductKey !== null],
    }),
    // NOTE: Not using `connect` here because the teamLogic might not have mounted yet
    // by the time this logic is mounted
    listeners(({ actions }) => ({
        markTaskAsCompleted: async ({ taskId }) => {
            const teamLogic = globalTeamLogic.findMounted()
            if (!teamLogic) {
                return
            }

            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam || !('onboarding_tasks' in currentTeam)) {
                return
            }

            // Check if already completed
            const existingStatus = currentTeam.onboarding_tasks?.[taskId]
            if (existingStatus === ActivationTaskStatus.COMPLETED) {
                return
            }

            // Track analytics
            posthog.capture('product setup task completed', { task: taskId })

            // Update team with completed task
            const onboardingTasks = {
                ...currentTeam.onboarding_tasks,
                [taskId]: ActivationTaskStatus.COMPLETED,
            }

            teamLogic.actions.updateCurrentTeam({ onboarding_tasks: onboardingTasks })

            // Reopen the quick start popover to show progress
            actions.openGlobalSetup()
        },

        markTaskAsSkipped: async ({ taskIdOrIds }) => {
            const teamLogic = globalTeamLogic.findMounted()
            if (!teamLogic) {
                return
            }

            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam || !('onboarding_tasks' in currentTeam)) {
                return
            }

            // Normalize to array for uniform handling
            const taskIds = Array.isArray(taskIdOrIds) ? taskIdOrIds : [taskIdOrIds]

            // Filter out already skipped tasks
            const tasksToSkip = taskIds.filter(
                (taskId) => currentTeam.onboarding_tasks?.[taskId] !== ActivationTaskStatus.SKIPPED
            )

            if (tasksToSkip.length === 0) {
                return
            }

            // Track analytics for each task
            for (const taskId of tasksToSkip) {
                posthog.capture('product setup task skipped', { task: taskId })
            }

            // Build the updated onboarding_tasks with all tasks marked as skipped
            const onboardingTasks = { ...currentTeam.onboarding_tasks }
            for (const taskId of tasksToSkip) {
                onboardingTasks[taskId] = ActivationTaskStatus.SKIPPED
            }

            teamLogic.actions.updateCurrentTeam({ onboarding_tasks: onboardingTasks })
        },

        unmarkTaskAsCompleted: async ({ taskId }) => {
            const teamLogic = globalTeamLogic.findMounted()
            if (!teamLogic) {
                return
            }

            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam || !('onboarding_tasks' in currentTeam)) {
                return
            }

            // Check if actually completed
            const existingStatus = currentTeam.onboarding_tasks?.[taskId]
            if (existingStatus !== ActivationTaskStatus.COMPLETED) {
                return
            }

            // Track analytics
            posthog.capture('product setup task uncompleted', { task: taskId })

            // Remove the completed status
            const onboardingTasks = { ...currentTeam.onboarding_tasks }
            delete onboardingTasks[taskId]

            teamLogic.actions.updateCurrentTeam({ onboarding_tasks: onboardingTasks })
        },

        unmarkTaskAsSkipped: async ({ taskId }) => {
            const teamLogic = globalTeamLogic.findMounted()
            if (!teamLogic) {
                return
            }

            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam || !('onboarding_tasks' in currentTeam)) {
                return
            }

            // Check if actually skipped
            const existingStatus = currentTeam.onboarding_tasks?.[taskId]
            if (existingStatus !== ActivationTaskStatus.SKIPPED) {
                return
            }

            // Track analytics
            posthog.capture('product setup task unskipped', { task: taskId })

            // Remove the skipped status
            const onboardingTasks = { ...currentTeam.onboarding_tasks }
            delete onboardingTasks[taskId]

            teamLogic.actions.updateCurrentTeam({ onboarding_tasks: onboardingTasks })
        },
    })),
])
