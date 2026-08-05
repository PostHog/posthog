/**
 * The goals a user can declare when entering the self-driving onboarding. Each goal is modeled as
 * something that is clearly achieved or not: `done` names the observable finish line the flow
 * drives toward (and what time-to-goal is measured against). The selection personalizes the rest
 * of the flow: step order, goal-conditional steps, and which product intent counts as primary.
 */
import { ProductKey } from '~/queries/schema/schema-general'

export type SelfDrivingGoal = 'user_behavior' | 'fix_issues' | 'website_traffic' | 'ai_app'

/** Stamped on every intent the self-driving onboarding registers, mirroring the flow's event props. */
export const SELF_DRIVING_INTENT_METADATA = { flow_variant: 'context_first' }

/** The product whose activation the goal is really about - registered as the primary intent. */
export const GOAL_PRIMARY_PRODUCT: Record<SelfDrivingGoal, ProductKey> = {
    user_behavior: ProductKey.PRODUCT_ANALYTICS,
    fix_issues: ProductKey.ERROR_TRACKING,
    website_traffic: ProductKey.WEB_ANALYTICS,
    ai_app: ProductKey.AI_OBSERVABILITY,
}

/** The team toggles a tool can sit behind (the product_enablement API's product names). */
export type EnablementProduct = 'session_replay' | 'error_tracking'

export type SelfDrivingToolKey =
    | 'product_analytics'
    | 'session_replay'
    | 'error_tracking'
    | 'web_analytics'
    | 'ai_observability'

export interface SelfDrivingTool {
    productKey: ProductKey
    name: string
    /** One line: what the tool contributes to the self-driving loop. */
    benefit: string
    /** Product icon key for `iconForType`. */
    iconType: 'product_analytics' | 'session_replay' | 'error_tracking' | 'web_analytics' | 'llm_analytics'
    docsUrl: string
    /** The team toggle behind the tool, when it needs one. Tools without one are on as soon as data flows. */
    enablement?: EnablementProduct
}

/** Every tool the onboarding can configure and show. */
export const SELF_DRIVING_TOOLS: Record<SelfDrivingToolKey, SelfDrivingTool> = {
    product_analytics: {
        productKey: ProductKey.PRODUCT_ANALYTICS,
        name: 'Product analytics',
        benefit: 'Events, trends, and funnels start flowing as soon as the SDK is in.',
        iconType: 'product_analytics',
        docsUrl: 'https://posthog.com/docs/product-analytics',
    },
    session_replay: {
        productKey: ProductKey.SESSION_REPLAY,
        name: 'Session replay',
        benefit: 'Real sessions recorded, so agents can watch what users did.',
        iconType: 'session_replay',
        docsUrl: 'https://posthog.com/docs/session-replay',
        enablement: 'session_replay',
    },
    error_tracking: {
        productKey: ProductKey.ERROR_TRACKING,
        name: 'Error tracking',
        benefit: 'Exceptions grouped into issues that feed your agents.',
        iconType: 'error_tracking',
        docsUrl: 'https://posthog.com/docs/error-tracking',
        enablement: 'error_tracking',
    },
    web_analytics: {
        productKey: ProductKey.WEB_ANALYTICS,
        name: 'Web analytics',
        benefit: 'Traffic, sources, and conversion on a live dashboard.',
        iconType: 'web_analytics',
        docsUrl: 'https://posthog.com/docs/web-analytics',
    },
    ai_observability: {
        productKey: ProductKey.AI_OBSERVABILITY,
        name: 'AI observability',
        benefit: 'Traces, costs, and failures from your LLM features.',
        iconType: 'llm_analytics',
        docsUrl: 'https://posthog.com/docs/llm-analytics',
    },
}

export interface SelfDrivingToolSet {
    /** Rendered on the tools step as the goal's configured collection; toggleable ones get auto-enabled. */
    shown: SelfDrivingToolKey[]
    /** Intent-only: these ProductKeys populate the sidebar but never appear in the onboarding UI.
     * Sidebar items resolve through the products registry's `intents` - e.g. a PRODUCT_ANALYTICS
     * intent brings both "Product analytics" and "Dashboards" into the sidebar. */
    sidebar: ProductKey[]
}

// Dashboards for everyone: it answers to the PRODUCT_ANALYTICS intent in the products registry.
const SHARED_SIDEBAR: ProductKey[] = [ProductKey.PRODUCT_ANALYTICS]

/** Docs pages for sidebar items resolved from the products registry, keyed by their registry path.
 * Tools in `SELF_DRIVING_TOOLS` carry their own `docsUrl`; this covers the sidebar-only extras. */
export const SIDEBAR_ITEM_DOCS_URL: Record<string, string> = {
    Dashboards: 'https://posthog.com/docs/product-analytics/dashboards',
    'Product analytics': 'https://posthog.com/docs/product-analytics',
}

const GOAL_TOOL_SETS: Record<SelfDrivingGoal, SelfDrivingToolSet> = {
    user_behavior: { shown: ['product_analytics', 'session_replay'], sidebar: SHARED_SIDEBAR },
    fix_issues: { shown: ['error_tracking', 'session_replay'], sidebar: SHARED_SIDEBAR },
    website_traffic: { shown: ['web_analytics', 'product_analytics'], sidebar: SHARED_SIDEBAR },
    ai_app: { shown: ['ai_observability', 'product_analytics'], sidebar: SHARED_SIDEBAR },
}

/** The "set up everything" path (no declared goal). */
const DEFAULT_TOOL_SET: SelfDrivingToolSet = {
    shown: ['product_analytics', 'session_replay', 'error_tracking'],
    sidebar: SHARED_SIDEBAR,
}

export function toolSetForGoal(goal: SelfDrivingGoal | null): SelfDrivingToolSet {
    return goal ? GOAL_TOOL_SETS[goal] : DEFAULT_TOOL_SET
}

export interface SelfDrivingGoalDefinition {
    key: SelfDrivingGoal
    title: string
    /** One sentence: how agents get there, ending in the deliverable (the goal's finish line). */
    description: string
    /** The achievement criterion (measurement spec, not rendered): the observable event that marks the goal done. */
    done: string
    /** Product icon key for `iconForType`. */
    iconType: 'product_analytics' | 'error_tracking' | 'web_analytics' | 'llm_analytics'
}

export const SELF_DRIVING_GOALS: SelfDrivingGoalDefinition[] = [
    {
        key: 'user_behavior',
        title: 'See how people use my product',
        description: 'Agents watch your events and sessions, and deliver your first report on real usage.',
        done: 'first behavior insight or report with real data',
        iconType: 'product_analytics',
    },
    {
        key: 'fix_issues',
        title: 'Fix a real issue in my product',
        description: 'Agents turn errors and broken sessions into signals, and open the first fix as a pull request.',
        done: 'first agent-opened fix pull request',
        iconType: 'error_tracking',
    },
    {
        key: 'website_traffic',
        title: 'See my website traffic',
        description: 'Traffic, sources, and conversion on a live dashboard as soon as data arrives.',
        done: 'web analytics dashboard showing real pageviews',
        iconType: 'web_analytics',
    },
    {
        key: 'ai_app',
        title: 'See what my AI app is doing',
        description: 'Traces, costs, and failures from your LLM features, from the first trace in.',
        done: 'first AI traces ingested',
        iconType: 'llm_analytics',
    },
]
