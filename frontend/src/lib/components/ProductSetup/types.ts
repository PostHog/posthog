import type { ReactNode } from 'react'

import type { AvailableSetupTaskIdsEnumApi } from '~/generated/core/api.schemas'
import type { ProductKey } from '~/queries/schema/schema-general'

export type SetupTaskId = AvailableSetupTaskIdsEnumApi

/**
 * Type of task - determines when/where it appears:
 * - setup: Mandatory configuration tasks that everyone needs to do once
 *   Examples: Install SDK, enable recordings, configure domains
 * - onboarding: Guidance for getting started when product is empty
 *   Examples: Create first insight, watch first recording, create first survey
 * - explore: Advanced/optional features to try after getting started
 *   Examples: Create funnel, set up cohorts, create multivariate flag
 */
export type TaskType = 'setup' | 'onboarding' | 'explore'

/** Definition of a single setup task */
export interface SetupTask {
    /** Unique task identifier - use SetupTaskId enum values */
    id: SetupTaskId
    /** Display title */
    title: string
    /** Help text or description */
    description: string | ReactNode
    /**
     * Warning message to show when user tries to skip this task.
     * If set, a confirmation dialog will be shown before skipping.
     * Tasks without this can be skipped without warning.
     */
    skipWarning?: string
    /**
     * Task type:
     * - 'setup': Mandatory configuration (install SDK, enable features)
     * - 'onboarding': Getting started guidance (create first X, explore Y)
     * Defaults to 'onboarding' if not specified
     */
    taskType?: TaskType
    /** Task IDs that must complete first - use SetupTaskId enum values */
    dependsOn?: SetupTaskId[]
    /** External documentation URL (opens in new tab) */
    docsUrl?: string
    /** Icon for the task */
    icon?: ReactNode
    /** Function that returns the internal URL to navigate to when task is clicked */
    getUrl?: () => string
    /**
     * CSS selector for the element to highlight after navigation.
     * Used to draw attention to the relevant UI element when user runs the task.
     */
    targetSelector?: string
    /**
     * Whether this task requires manual completion by the user.
     * Manual tasks show a checkbox icon and can be marked complete/incomplete by the user.
     * Non-manual tasks are auto-completed by tracking user actions.
     */
    requiresManualCompletion?: boolean
}

/** Runtime state of a setup task (definition + current state) */
export interface SetupTaskWithState extends SetupTask {
    /** Whether task is completed */
    completed: boolean
    /** Whether task was skipped */
    skipped: boolean
    /** If locked, the reason why */
    lockedReason?: string
}

/** Configuration for a product's setup experience */
export interface ProductSetupConfig {
    /** The product key this config is for */
    productKey: ProductKey
    /** Display title, e.g., "Get started with Product analytics" */
    title: string
    /**
     * All tasks for this product, organized by type.
     * Use taskType field to categorize: 'setup', 'onboarding', or 'explore'
     */
    tasks: SetupTask[]
}
