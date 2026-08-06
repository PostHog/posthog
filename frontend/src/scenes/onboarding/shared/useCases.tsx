/**
 * The declarative model the onboarding spins off from. A use case defines which tools it contains,
 * which extras go to the sidebar, and (through each tool's `options`) which team settings must be
 * on for self-driving to actually see data. Tool display (name, icon) resolves from the products
 * registry via `productPath`, so the flow can't drift from the sidebar.
 */
import { getTreeItemsProducts } from '~/products'
import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

export type OnboardingUseCaseKey = 'user_behavior' | 'fix_issues' | 'website_traffic' | 'ai_app'

/** Stamped on every intent the self-driving onboarding registers, mirroring the flow's event props. */
export const SELF_DRIVING_INTENT_METADATA = { flow_variant: 'context_first' }

/** A team setting a tool needs to produce data. Keys are ours; each maps to a `Team` field. */
export type TeamOption =
    | 'session_recording' // session_recording_opt_in
    | 'replay_masking_floor' // session_recording_masking_config, only if unset
    | 'console_log_capture' // capture_console_log_opt_in (admin-gated)
    | 'network_performance' // capture_performance_opt_in (admin-gated)
    | 'exception_autocapture' // autocapture_exceptions_opt_in
    | 'heatmaps' // heatmaps_opt_in (admin-gated)
    | 'dead_clicks' // capture_dead_clicks (admin-gated)
    | 'web_vitals' // autocapture_web_vitals_opt_in

/** The product_enablement API's product names. */
export type EnablementProduct = 'session_replay' | 'error_tracking'

export type OnboardingToolKey =
    | 'product_analytics'
    | 'session_replay'
    | 'error_tracking'
    | 'web_analytics'
    | 'ai_observability'

export interface OnboardingTool {
    /** `path` of the tool's entry in the products registry (`getTreeItemsProducts()`) - the
     * display name, and where icon, docs, and sidebar item resolve from. */
    productPath: string
    productKey: ProductKey
    /** One line: what the tool contributes to the self-driving loop. */
    benefit: string
    /** Everything that must be on for this tool to work. */
    options: TeamOption[]
}

export const ONBOARDING_TOOLS: Record<OnboardingToolKey, OnboardingTool> = {
    product_analytics: {
        productPath: 'Product analytics',
        productKey: ProductKey.PRODUCT_ANALYTICS,
        benefit: 'Events, trends, and funnels start flowing as soon as the SDK is in.',
        options: ['heatmaps', 'dead_clicks'],
    },
    session_replay: {
        productPath: 'Session replay',
        productKey: ProductKey.SESSION_REPLAY,
        benefit: 'Real sessions recorded, so agents can watch what users did.',
        options: ['session_recording', 'replay_masking_floor', 'console_log_capture', 'network_performance'],
    },
    error_tracking: {
        productPath: 'Error tracking',
        productKey: ProductKey.ERROR_TRACKING,
        benefit: 'Exceptions grouped into issues that feed your agents.',
        options: ['exception_autocapture'],
    },
    web_analytics: {
        productPath: 'Web analytics',
        productKey: ProductKey.WEB_ANALYTICS,
        benefit: 'Traffic, sources, and conversion on a live dashboard.',
        options: ['web_vitals', 'heatmaps', 'network_performance'],
    },
    ai_observability: {
        productPath: 'LLM analytics',
        productKey: ProductKey.AI_OBSERVABILITY,
        benefit: 'Traces, costs, and failures from your LLM features.',
        options: [],
    },
}

/** Docs pages, keyed by products-registry path - covers tools and sidebar-only extras alike. */
export const DOCS_URL_BY_PRODUCT_PATH: Record<string, string> = {
    'Product analytics': 'https://posthog.com/docs/product-analytics',
    'Session replay': 'https://posthog.com/docs/session-replay',
    'Error tracking': 'https://posthog.com/docs/error-tracking',
    'Web analytics': 'https://posthog.com/docs/web-analytics',
    'LLM analytics': 'https://posthog.com/docs/llm-analytics',
    Dashboards: 'https://posthog.com/docs/product-analytics/dashboards',
}

export function toolIconType(tool: OnboardingTool): FileSystemIconType {
    const item = getTreeItemsProducts().find((i) => i.path === tool.productPath)
    return item?.iconType ?? 'product_analytics'
}

/** A flow step only some use cases need; the flow maps each id to its step component. */
export type OnboardingExtraStepId = 'authorized-urls' | 'ai-observability'

/** What a selection sets up, shared by the use cases and the no-use-case default. */
export interface OnboardingSetup {
    /** Registered as the primary product intent. */
    primaryProduct: ProductKey
    /** Shown and configured on the tools step. */
    tools: OnboardingToolKey[]
    /** Intent-only ProductKeys: populate the sidebar (via the products registry's `intents`)
     * without appearing in the onboarding UI. */
    sidebarExtras: ProductKey[]
    /** Team settings needed beyond the tools' own options. */
    extraOptions?: TeamOption[]
    /** Steps after install that this setup can't reach its finish line without. */
    extraSteps?: OnboardingExtraStepId[]
}

export interface OnboardingUseCase extends OnboardingSetup {
    key: OnboardingUseCaseKey
    title: string
    /** One sentence: how agents get there, ending in the deliverable (the finish line). */
    description: string
    /** The achievement criterion (measurement spec, not rendered). */
    done: string
}

// Dashboards for everyone: it answers to the PRODUCT_ANALYTICS intent in the products registry.
const SHARED_SIDEBAR: ProductKey[] = [ProductKey.PRODUCT_ANALYTICS]

export const ONBOARDING_USE_CASES: OnboardingUseCase[] = [
    {
        key: 'user_behavior',
        title: 'See how people use my product',
        description: 'Agents watch your events and sessions, and deliver your first report on real usage.',
        done: 'first behavior insight or report with real data',
        primaryProduct: ProductKey.PRODUCT_ANALYTICS,
        tools: ['product_analytics', 'session_replay'],
        sidebarExtras: SHARED_SIDEBAR,
    },
    {
        key: 'fix_issues',
        title: 'Fix a real issue in my product',
        description: 'Agents turn errors and broken sessions into signals, and open the first fix as a pull request.',
        done: 'first agent-opened fix pull request',
        primaryProduct: ProductKey.ERROR_TRACKING,
        tools: ['error_tracking', 'session_replay'],
        sidebarExtras: SHARED_SIDEBAR,
    },
    {
        key: 'website_traffic',
        title: 'See my website traffic',
        description: 'Traffic, sources, and conversion on a live dashboard as soon as data arrives.',
        done: 'web analytics dashboard showing real pageviews',
        primaryProduct: ProductKey.WEB_ANALYTICS,
        tools: ['web_analytics', 'product_analytics'],
        sidebarExtras: SHARED_SIDEBAR,
        // Web analytics needs at least one authorized URL before its dashboard can show anything.
        extraSteps: ['authorized-urls'],
    },
    {
        key: 'ai_app',
        title: 'See what my AI app is doing',
        description: 'Traces, costs, and failures from your LLM features, from the first trace in.',
        done: 'first AI traces ingested',
        primaryProduct: ProductKey.AI_OBSERVABILITY,
        tools: ['ai_observability', 'product_analytics'],
        sidebarExtras: SHARED_SIDEBAR,
        // The generic wizard install doesn't wire LLM instrumentation - without this step the
        // finish line (first AI traces) is unreachable.
        extraSteps: ['ai-observability'],
    },
]

/** The "set up everything" path (no declared use case). */
const DEFAULT_SETUP: OnboardingSetup = {
    primaryProduct: ProductKey.PRODUCT_ANALYTICS,
    tools: ['product_analytics', 'session_replay', 'error_tracking'],
    sidebarExtras: SHARED_SIDEBAR,
}

export function resolveSetup(useCase: OnboardingUseCaseKey | null): OnboardingSetup {
    return ONBOARDING_USE_CASES.find((u) => u.key === useCase) ?? DEFAULT_SETUP
}

/** The setup's primary tool - the use-case card's icon derives from it. */
export function primaryTool(setup: OnboardingSetup): OnboardingTool {
    const key = setup.tools.find((k) => ONBOARDING_TOOLS[k].productKey === setup.primaryProduct) ?? setup.tools[0]
    return ONBOARDING_TOOLS[key]
}

/** Every team option the setup needs: the tools' union plus the setup's extras. */
export function optionsForSetup(setup: OnboardingSetup): TeamOption[] {
    return Array.from(
        new Set([...setup.tools.flatMap((key) => ONBOARDING_TOOLS[key].options), ...(setup.extraOptions ?? [])])
    )
}

/** The product_enablement recipe covering the tool's options, when one exists. */
export function toolEnablement(tool: OnboardingTool): EnablementProduct | undefined {
    if (tool.options.includes('session_recording')) {
        return 'session_replay'
    }
    if (tool.options.includes('exception_autocapture')) {
        return 'error_tracking'
    }
    return undefined
}
