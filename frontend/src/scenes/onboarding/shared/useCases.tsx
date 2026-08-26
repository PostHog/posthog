/**
 * The declarative model the onboarding spins off from. A use case defines which tools it contains,
 * which extras go to the sidebar, and (through each tool's `options`) which team settings must be
 * on for self-driving to actually see data. Tool display (name, icon) resolves from the products
 * registry via `productPath`, so the flow can't drift from the sidebar.
 */
import { getTreeItemsProducts } from '~/products'
import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

export type OnboardingUseCaseKey =
    | 'find_problems'
    | 'improve_experience'
    | 'ship_changes'
    | 'maintain_ai'
    | 'connect_context'
    | 'ai_app'

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

export type OnboardingToolKey =
    | 'product_analytics'
    | 'session_replay'
    | 'error_tracking'
    | 'web_analytics'
    | 'ai_observability'

export interface OnboardingTool {
    productPath: string
    displayName?: string
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
        benefit: 'Events, trends, and funnels. Understand how users use your product.',
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
        displayName: 'AI observability',
        productKey: ProductKey.AI_OBSERVABILITY,
        benefit: 'Traces, costs, and failures from your LLM features.',
        options: [],
    },
}

export const SUPPORTED_TOOL_PRODUCTS = [
    ...Object.values(ONBOARDING_TOOLS).map((tool) => tool.productKey),
    ProductKey.FEATURE_FLAGS,
    ProductKey.EXPERIMENTS,
    ProductKey.SURVEYS,
    ProductKey.LOGS,
    ProductKey.METRICS,
    ProductKey.DATA_WAREHOUSE,
    ProductKey.WORKFLOWS,
    ProductKey.MCP_ANALYTICS,
    ProductKey.CONVERSATIONS,
]

export const ADDITIONAL_TOOL_DETAILS: Partial<Record<ProductKey, { description: string; docsUrl: string }>> = {
    [ProductKey.FEATURE_FLAGS]: {
        description: 'Roll out changes gradually and safely.',
        docsUrl: 'https://posthog.com/docs/feature-flags',
    },
    [ProductKey.EXPERIMENTS]: {
        description: 'Measure whether a product change works.',
        docsUrl: 'https://posthog.com/docs/experiments',
    },
    [ProductKey.SURVEYS]: {
        description: 'Collect feedback from users in your product.',
        docsUrl: 'https://posthog.com/docs/surveys',
    },
    [ProductKey.LOGS]: {
        description: 'Search and investigate application logs.',
        docsUrl: 'https://posthog.com/docs/logs',
    },
    [ProductKey.METRICS]: {
        description: 'Monitor service metrics and alerts.',
        docsUrl: 'https://posthog.com/docs/metrics',
    },
    [ProductKey.DATA_WAREHOUSE]: {
        description: 'Query product and business data together.',
        docsUrl: 'https://posthog.com/docs/data-warehouse',
    },
    [ProductKey.WORKFLOWS]: {
        description: 'Automate work from product activity.',
        docsUrl: 'https://posthog.com/docs/workflows',
    },
    [ProductKey.MCP_ANALYTICS]: {
        description: 'Monitor MCP tool calls and failures.',
        docsUrl: 'https://posthog.com/docs/mcp-analytics',
    },
    [ProductKey.CONVERSATIONS]: {
        description: 'Manage support conversations with customers.',
        docsUrl: 'https://posthog.com/docs/support',
    },
}

/** Docs pages, keyed by products-registry path - covers tools and sidebar-only extras alike. */
export const DOCS_URL_BY_PRODUCT_PATH: Record<string, string> = {
    'Product analytics': 'https://posthog.com/docs/product-analytics',
    'Session replay': 'https://posthog.com/docs/session-replay',
    'Error tracking': 'https://posthog.com/docs/error-tracking',
    'Web analytics': 'https://posthog.com/docs/web-analytics',
    'LLM analytics': 'https://posthog.com/docs/llm-analytics',
    'Feature flags': 'https://posthog.com/docs/feature-flags',
    Experiments: 'https://posthog.com/docs/experiments',
    Surveys: 'https://posthog.com/docs/surveys',
    Logs: 'https://posthog.com/docs/logs',
    Metrics: 'https://posthog.com/docs/metrics',
    'Data warehouse': 'https://posthog.com/docs/data-warehouse',
    Workflows: 'https://posthog.com/docs/workflows',
    'MCP analytics': 'https://posthog.com/docs/mcp-analytics',
    Support: 'https://posthog.com/docs/support',
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
    /** Intent-only ProductKeys shown on the tools step. */
    additionalTools?: ProductKey[]
    /** Intent-only ProductKeys: populate the sidebar (via the products registry's `intents`)
     * without appearing in the onboarding UI. */
    sidebarExtras: ProductKey[]
    /** Team settings needed beyond the tools' own options. */
    extraOptions?: TeamOption[]
    /** Steps after install that this setup can't reach its finish line without. */
    extraSteps?: OnboardingExtraStepId[]
}

export function productKeysForSetup(setup: OnboardingSetup): ProductKey[] {
    return Array.from(
        new Set([
            setup.primaryProduct,
            ...setup.tools.map((key) => ONBOARDING_TOOLS[key].productKey),
            ...(setup.additionalTools ?? []),
            ...setup.sidebarExtras,
        ])
    )
}

export interface OnboardingUseCase extends OnboardingSetup {
    key: OnboardingUseCaseKey
    icon: FileSystemIconType
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
        key: 'improve_experience',
        icon: 'product_analytics',
        title: 'Improve the customer experience',
        description: 'Agents study behavior, feedback, traffic, and conversions. They identify where users get stuck.',
        done: 'first experience finding or report',
        primaryProduct: ProductKey.PRODUCT_ANALYTICS,
        tools: ['product_analytics', 'session_replay', 'web_analytics'],
        additionalTools: [ProductKey.SURVEYS],
        sidebarExtras: SHARED_SIDEBAR,
        extraSteps: ['authorized-urls'],
    },
    {
        key: 'find_problems',
        icon: 'error_tracking',
        title: 'Find product problems',
        description:
            'Agents inspect errors, sessions, logs, and support context. They send findings and propose fixes.',
        done: 'first product problem finding or proposed fix',
        primaryProduct: ProductKey.ERROR_TRACKING,
        tools: ['error_tracking', 'session_replay'],
        additionalTools: [ProductKey.LOGS, ProductKey.METRICS, ProductKey.CONVERSATIONS],
        sidebarExtras: SHARED_SIDEBAR,
    },
    {
        key: 'ship_changes',
        icon: 'feature_flag',
        title: 'Ship changes with confidence',
        description: 'Agents monitor flags and experiments. They report results before you expand a rollout.',
        done: 'first rollout or experiment result',
        primaryProduct: ProductKey.FEATURE_FLAGS,
        tools: ['product_analytics'],
        additionalTools: [ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS],
        sidebarExtras: SHARED_SIDEBAR,
    },
    {
        key: 'maintain_ai',
        icon: 'llm_analytics',
        title: 'Maintain an AI product',
        description: 'Agents inspect AI traces, costs, failures, and MCP tool calls. They find issues in AI features.',
        done: 'first AI product finding or report',
        primaryProduct: ProductKey.AI_OBSERVABILITY,
        tools: ['ai_observability', 'product_analytics'],
        additionalTools: [ProductKey.MCP_ANALYTICS],
        sidebarExtras: SHARED_SIDEBAR,
        extraSteps: ['ai-observability'],
    },
    {
        key: 'connect_context',
        icon: 'data_warehouse',
        title: 'Connect context and automate work',
        description: 'Agents use warehouse data and workflows to act on signals across your systems.',
        done: 'first workflow or report using connected context',
        primaryProduct: ProductKey.DATA_WAREHOUSE,
        tools: ['product_analytics'],
        additionalTools: [ProductKey.DATA_WAREHOUSE, ProductKey.WORKFLOWS],
        sidebarExtras: SHARED_SIDEBAR,
    },
]

const DEFAULT_SETUP: OnboardingSetup = {
    primaryProduct: ProductKey.PRODUCT_ANALYTICS,
    tools: ['product_analytics', 'session_replay', 'error_tracking'],
    additionalTools: [
        ProductKey.FEATURE_FLAGS,
        ProductKey.EXPERIMENTS,
        ProductKey.SURVEYS,
        ProductKey.LOGS,
        ProductKey.METRICS,
        ProductKey.DATA_WAREHOUSE,
        ProductKey.WORKFLOWS,
        ProductKey.MCP_ANALYTICS,
        ProductKey.CONVERSATIONS,
        ProductKey.WEB_ANALYTICS,
        ProductKey.AI_OBSERVABILITY,
    ],
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
