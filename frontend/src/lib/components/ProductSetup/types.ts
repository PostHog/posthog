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
 * - ai: PostHog's AI surfaces, shown for every product
 *   Examples: PostHog AI, PostHog Desktop, PostHog MCP, PostHog in Slack
 */
export type TaskType = 'setup' | 'onboarding' | 'explore' | 'ai'

export interface SetupTask {
    id: SetupTaskId
    title: string
    description: string | ReactNode
    /**
     * Warning message to show when user tries to skip this task.
     * If set, a confirmation dialog will be shown before skipping.
     * Tasks without this can be skipped without warning.
     */
    skipWarning?: string
    /** Defaults to 'onboarding' if not specified */
    taskType?: TaskType
    /** Tasks that must be completed before this one unlocks */
    dependsOn?: SetupTaskId[]
    /** External documentation URL, opened in a new tab. Only used when getUrl is not set. */
    docsUrl?: string
    icon?: ReactNode
    /** Internal URL to navigate to when the task is clicked */
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

export interface SetupTaskWithState extends SetupTask {
    completed: boolean
    skipped: boolean
    /** Set while a task in dependsOn is still incomplete. The task is unlocked when this is absent. */
    lockedReason?: string
}

export interface ProductSetupConfig {
    productKey: ProductKey
    title: string
    tasks: SetupTask[]
}

/** A pending attention highlight, bound to the route that asked for it */
export interface SetupHighlight {
    selector: string
    /** Route the highlight belongs to - the highlight drops when the user leaves it */
    pathname: string
}
