import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { sceneLogic } from 'scenes/sceneLogic'
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
            const teamLogic = globalTeamLogic.findMounted()
            if (!teamLogic) {
                return
            }

            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam || !('onboarding_tasks' in currentTeam)) {
                return
            }

            const taskIds = Array.isArray(taskIdOrIds) ? taskIdOrIds : [taskIdOrIds]

            // Filter out already completed tasks
            const tasksToComplete = taskIds.filter(
                (taskId) => currentTeam.onboarding_tasks?.[taskId] !== ActivationTaskStatus.COMPLETED
            )

            if (tasksToComplete.length === 0) {
                return
            }

            // Track analytics for each task
            for (const taskId of tasksToComplete) {
                posthog.capture('product setup task completed', { task: taskId })
            }

            // Update team with completed tasks
            const onboardingTasks = { ...currentTeam.onboarding_tasks }
            for (const taskId of tasksToComplete) {
                onboardingTasks[taskId] = ActivationTaskStatus.COMPLETED
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

            // Update team with skipped tasks
            const onboardingTasks = { ...currentTeam.onboarding_tasks }
            for (const taskId of tasksToSkip) {
                onboardingTasks[taskId] = ActivationTaskStatus.SKIPPED
            }

            teamLogic.actions.updateCurrentTeam({ onboarding_tasks: onboardingTasks })
        },

        unmarkTaskAsCompleted: async ({ taskIdOrIds }) => {
            const teamLogic = globalTeamLogic.findMounted()
            if (!teamLogic) {
                return
            }

            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam || !('onboarding_tasks' in currentTeam)) {
                return
            }

            const taskIds = Array.isArray(taskIdOrIds) ? taskIdOrIds : [taskIdOrIds]

            // Filter to only actually completed tasks
            const tasksToUncomplete = taskIds.filter(
                (taskId) => currentTeam.onboarding_tasks?.[taskId] === ActivationTaskStatus.COMPLETED
            )

            if (tasksToUncomplete.length === 0) {
                return
            }

            // Track analytics for each task
            for (const taskId of tasksToUncomplete) {
                posthog.capture('product setup task uncompleted', { task: taskId })
            }

            // Remove the completed status
            const onboardingTasks = { ...currentTeam.onboarding_tasks }
            for (const taskId of tasksToUncomplete) {
                delete onboardingTasks[taskId]
            }

            teamLogic.actions.updateCurrentTeam({ onboarding_tasks: onboardingTasks })
        },

        unmarkTaskAsSkipped: async ({ taskIdOrIds }) => {
            const teamLogic = globalTeamLogic.findMounted()
            if (!teamLogic) {
                return
            }

            const currentTeam = teamLogic.values.currentTeam
            if (!currentTeam || !('onboarding_tasks' in currentTeam)) {
                return
            }

            const taskIds = Array.isArray(taskIdOrIds) ? taskIdOrIds : [taskIdOrIds]

            // Filter to only actually skipped tasks
            const tasksToUnskip = taskIds.filter(
                (taskId) => currentTeam.onboarding_tasks?.[taskId] === ActivationTaskStatus.SKIPPED
            )

            if (tasksToUnskip.length === 0) {
                return
            }

            // Track analytics for each task
            for (const taskId of tasksToUnskip) {
                posthog.capture('product setup task unskipped', { task: taskId })
            }

            // Remove the skipped status
            const onboardingTasks = { ...currentTeam.onboarding_tasks }
            for (const taskId of tasksToUnskip) {
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
])
