import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { addProductIntent } from 'lib/utils/product-intents'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { availableOnboardingProducts, toSentenceCase } from 'scenes/onboarding/shared/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import type { CyclotronJobFiltersType, OnboardingProduct, TeamPublicType, TeamType } from '~/types'

import { ERROR_TRACKING_SUB_TEMPLATE_IDS } from 'products/error_tracking/frontend/scenes/ErrorTrackingConfigurationScene/alerting/alertWizardConfig'

import { PublicationFeedKey, QuickstartPublication, fetchPublicationsPage } from './publications'
import type { quickstartLogicType } from './quickstartLogicType'

/** How far along the activation ladder a tool is. Quality lives past 'live', not as extra levels. */
export type QuickstartToolLevel = 'needs_setup' | 'ready' | 'live'

/** Which primary action the card should offer */
export type QuickstartToolCta = 'install' | 'enable' | 'setup' | 'open'

/** Event-derived counters for the last 30 days */
export interface QuickstartToolSignals {
    totalEvents: number
    prodEvents: number
    customEvents: number
    distinctCustomEvents: number
    identifyCalls: number
    exceptions: number
    serverExceptions: number
    backendEvents: number
    flagCalls: number
    prodFlagCalls: number
    pageviews: number
    prodPageviews: number
    surveyResponses: number
    aiGenerations: number
    aiTraceEvents: number
    mcpInitialize: number
    mcpToolCalls: number
}

const EMPTY_TOOL_SIGNALS: QuickstartToolSignals = {
    totalEvents: 0,
    prodEvents: 0,
    customEvents: 0,
    distinctCustomEvents: 0,
    identifyCalls: 0,
    exceptions: 0,
    serverExceptions: 0,
    backendEvents: 0,
    flagCalls: 0,
    prodFlagCalls: 0,
    pageviews: 0,
    prodPageviews: 0,
    surveyResponses: 0,
    aiGenerations: 0,
    aiTraceEvents: 0,
    mcpInitialize: 0,
    mcpToolCalls: 0,
}

/** Non-event facts: resource counts and dedicated proof-of-life checks. Null while unknown. */
export interface QuickstartResources {
    replayRecordings: number | null
    hasLogs: boolean | null
    sourcesCount: number | null
    workflowsCount: number | null
    eventTriggeredWorkflows: number | null
    symbolSetsCount: number | null
    errorAlertsCount: number | null
    ticketsCount: number | null
}

const EMPTY_RESOURCES: QuickstartResources = {
    replayRecordings: null,
    hasLogs: null,
    sourcesCount: null,
    workflowsCount: null,
    eventTriggeredWorkflows: null,
    symbolSetsCount: null,
    errorAlertsCount: null,
    ticketsCount: null,
}

// The same hog function filters the error tracking alerting scene lists: an alert exists
// when a destination matches one of the product's alert sub-templates
const ERROR_TRACKING_ALERT_FILTERS = ERROR_TRACKING_SUB_TEMPLATE_IDS.map(getFiltersFromSubTemplateId).filter(
    (filters): filters is CyclotronJobFiltersType => !!filters
)

export interface QuickstartActivationData {
    signals: QuickstartToolSignals | null
    resources: QuickstartResources
}

interface StatusContext {
    team: TeamType
    signals: QuickstartToolSignals
    resources: QuickstartResources
}

/**
 * One rung of a tool's ladder. Activation rungs take the tool from nothing to live;
 * quality rungs deepen the data past that. The label doubles as the card's next step.
 */
interface ToolMilestone {
    key: string
    label: string
    achieved: (ctx: StatusContext) => boolean
}

export interface QuickstartToolStatus {
    level: QuickstartToolLevel
    /** Quality rungs achieved / total, meaningful once live. Total 0 hides the meter. */
    qualityAchieved: number
    qualityTotal: number
    /** The next rung worth climbing, activation first, then quality. Null when topped out. */
    nextStep: string | null
    /** The tool's headline number, e.g. sources connected or custom events captured */
    stat: { value: number; label: string } | null
    cta: QuickstartToolCta
}

export interface QuickstartProduct {
    key: ProductKey
    name: string
    description: string
    icon: string
    iconColor: string
    /** Short audience hint rendered as "Best for …" on the card */
    bestFor: string
    status: QuickstartToolStatus
    /** Whether the setup dialog with SDK instructions applies */
    requiresEvents: boolean
    /** Where "Open" points */
    url: string
    /** Where "Set up" points when the tool has a setup flow */
    setupUrl: string
    docsUrl?: string
}

interface QuickstartProductDefinition {
    bestFor: string
    docsUrl?: string
    /** Overrides the onboarding metadata copy when the quickstart card needs different framing */
    description?: string
    /** Team settings patched to turn the tool on in one click, with the predicate proving it's on */
    optInPayload?: Partial<TeamType>
    enabled?: (team: TeamType) => boolean
    /** The tool is pointless without SDK events, so its setup dialog shows install instructions */
    requiresEvents?: boolean
    /** Usable from day one with nothing configured (workflows, warehouse) — never below 'ready' */
    usableByDefault?: boolean
    /** Ordered rungs from nothing to live. The LAST rung is the proof-of-life signal. */
    activation: ToolMilestone[]
    /** Ordered rungs that deepen the data once live */
    quality: ToolMilestone[]
    stat?: (ctx: StatusContext) => { value: number; label: string } | null
}

function deriveToolStatus(definition: QuickstartProductDefinition, ctx: StatusContext): QuickstartToolStatus {
    const signalRung = definition.activation[definition.activation.length - 1]
    const earlierRungs = definition.activation.slice(0, -1)
    // The signal always wins: real data proves the tool works even if a setup rung
    // looks incomplete (e.g. server-side exceptions without the browser opt-in)
    const live = signalRung.achieved(ctx)

    let level: QuickstartToolLevel
    if (live) {
        level = 'live'
    } else if (earlierRungs.every((rung) => rung.achieved(ctx))) {
        level = 'ready'
    } else {
        level = definition.usableByDefault ? 'ready' : 'needs_setup'
    }

    const qualityAchieved = definition.quality.filter((rung) => rung.achieved(ctx)).length
    const nextStep = live
        ? (definition.quality.find((rung) => !rung.achieved(ctx))?.label ?? null)
        : (definition.activation.find((rung) => !rung.achieved(ctx))?.label ?? null)

    let cta: QuickstartToolCta
    if (definition.requiresEvents && !ctx.team.ingested_event) {
        cta = 'install'
    } else if (definition.optInPayload && definition.enabled && !definition.enabled(ctx.team)) {
        cta = 'enable'
    } else if (level === 'needs_setup') {
        cta = 'setup'
    } else {
        cta = 'open'
    }

    const stat = definition.stat?.(ctx) ?? null
    return {
        level,
        qualityAchieved,
        qualityTotal: definition.quality.length,
        nextStep,
        stat: stat && stat.value > 0 ? stat : null,
        cta,
    }
}

/** Display order: the tools most teams start with come first. */
export const QUICKSTART_PRODUCT_ORDER: ProductKey[] = [
    ProductKey.PRODUCT_ANALYTICS,
    ProductKey.WEB_ANALYTICS,
    ProductKey.SESSION_REPLAY,
    ProductKey.ERROR_TRACKING,
    ProductKey.FEATURE_FLAGS,
    ProductKey.SURVEYS,
    ProductKey.EXPERIMENTS,
    ProductKey.AI_OBSERVABILITY,
    ProductKey.DATA_WAREHOUSE,
    ProductKey.WORKFLOWS,
    ProductKey.LOGS,
    ProductKey.MCP_ANALYTICS,
    ProductKey.CONVERSATIONS,
]

// Shared rungs. Each is a plain predicate over the context, so ladders can reuse them freely.
const installAnySdk: ToolMilestone = {
    key: 'install_sdk',
    label: 'Install a PostHog SDK',
    achieved: ({ team }) => !!team.ingested_event,
}
const installWebSdk: ToolMilestone = {
    key: 'install_web_sdk',
    label: 'Install posthog-js on your site',
    achieved: ({ team }) => !!team.ingested_event,
}
const productionTraffic: ToolMilestone = {
    key: 'production_traffic',
    label: 'Deploy your instrumentation to production',
    achieved: ({ signals }) => signals.prodEvents > 0,
}
const firstCustomEvent: ToolMilestone = {
    key: 'first_custom_event',
    label: 'Capture your first custom event',
    achieved: ({ signals }) => signals.customEvents > 0,
}

const QUICKSTART_PRODUCT_DEFINITIONS: Partial<Record<ProductKey, QuickstartProductDefinition>> = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        bestFor: 'understanding user behavior',
        docsUrl: 'https://posthog.com/docs/product-analytics',
        requiresEvents: true,
        activation: [
            installAnySdk,
            { key: 'events', label: 'Capture your first event', achieved: ({ signals }) => signals.totalEvents > 0 },
        ],
        quality: [
            productionTraffic,
            firstCustomEvent,
            {
                key: 'custom_breadth',
                label: 'Track 5+ distinct custom events',
                achieved: ({ signals }) => signals.distinctCustomEvents >= 5,
            },
            {
                key: 'identify',
                label: 'Identify your users to unlock person-level analysis',
                achieved: ({ signals }) => signals.identifyCalls > 0,
            },
        ],
        stat: ({ signals }) => ({ value: signals.distinctCustomEvents, label: 'custom events' }),
    },
    [ProductKey.WEB_ANALYTICS]: {
        bestFor: 'marketing & traffic',
        docsUrl: 'https://posthog.com/docs/web-analytics',
        requiresEvents: true,
        activation: [
            installWebSdk,
            { key: 'pageviews', label: 'Get pageviews flowing', achieved: ({ signals }) => signals.pageviews > 0 },
        ],
        quality: [
            {
                key: 'prod_pageviews',
                label: 'Deploy to production to see real visitors',
                achieved: ({ signals }) => signals.prodPageviews > 0,
            },
            { ...firstCustomEvent, label: 'Capture custom events to measure conversions' },
        ],
        stat: ({ signals }) => ({ value: signals.pageviews, label: 'pageviews · 30d' }),
    },
    [ProductKey.SESSION_REPLAY]: {
        bestFor: 'debugging UX issues',
        docsUrl: 'https://posthog.com/docs/session-replay',
        requiresEvents: true,
        // Same payload the replay onboarding step applies
        optInPayload: {
            session_recording_opt_in: true,
            capture_console_log_opt_in: true,
            capture_performance_opt_in: true,
        },
        enabled: (team) => !!team.session_recording_opt_in,
        activation: [
            installWebSdk,
            {
                key: 'opt_in',
                label: 'Turn on session recordings',
                achieved: ({ team }) => !!team.session_recording_opt_in,
            },
            {
                key: 'recordings',
                label: 'Record your first session',
                achieved: ({ resources }) => (resources.replayRecordings ?? 0) > 0,
            },
        ],
        quality: [
            {
                key: 'console_logs',
                label: 'Capture console logs with recordings',
                achieved: ({ team }) => !!team.capture_console_log_opt_in,
            },
            {
                key: 'performance',
                label: 'Capture network performance with recordings',
                achieved: ({ team }) => !!team.capture_performance_opt_in,
            },
            productionTraffic,
        ],
        stat: ({ resources }) => ({ value: resources.replayRecordings ?? 0, label: 'recordings · 30d' }),
    },
    [ProductKey.ERROR_TRACKING]: {
        bestFor: 'catching bugs early',
        docsUrl: 'https://posthog.com/docs/error-tracking',
        requiresEvents: true,
        // Browser autocapture only: server SDKs capture exceptions without this opt-in
        optInPayload: { autocapture_exceptions_opt_in: true },
        enabled: (team) => !!team.autocapture_exceptions_opt_in,
        activation: [
            installAnySdk,
            {
                key: 'exceptions',
                label: 'Capture your first exception',
                achieved: ({ signals }) => signals.exceptions > 0,
            },
        ],
        quality: [
            {
                key: 'web_autocapture',
                label: 'Turn on exception autocapture for the web',
                achieved: ({ team }) => !!team.autocapture_exceptions_opt_in,
            },
            {
                key: 'server_exceptions',
                label: 'Capture exceptions from a server SDK too',
                achieved: ({ signals }) => signals.serverExceptions > 0,
            },
            {
                key: 'source_maps',
                label: 'Upload source maps for readable stack traces',
                achieved: ({ resources }) => (resources.symbolSetsCount ?? 0) > 0,
            },
            {
                key: 'alert',
                label: 'Set up an alert for new exceptions',
                achieved: ({ resources }) => (resources.errorAlertsCount ?? 0) > 0,
            },
            productionTraffic,
        ],
        stat: ({ signals }) => ({ value: signals.exceptions, label: 'exceptions · 30d' }),
    },
    [ProductKey.FEATURE_FLAGS]: {
        bestFor: 'safe rollouts',
        docsUrl: 'https://posthog.com/docs/feature-flags',
        requiresEvents: true,
        activation: [
            installAnySdk,
            {
                key: 'flag_called',
                label: 'Create a flag and call it from your code',
                achieved: ({ signals }) => signals.flagCalls > 0,
            },
        ],
        quality: [
            {
                key: 'prod_flag_calls',
                label: 'Evaluate flags in production',
                achieved: ({ signals }) => signals.prodFlagCalls > 0,
            },
        ],
        stat: ({ signals }) => ({ value: signals.flagCalls, label: 'flag calls · 30d' }),
    },
    [ProductKey.SURVEYS]: {
        bestFor: 'user feedback',
        docsUrl: 'https://posthog.com/docs/surveys',
        requiresEvents: true,
        optInPayload: { surveys_opt_in: true },
        enabled: (team) => !!team.surveys_opt_in,
        activation: [
            installWebSdk,
            { key: 'opt_in', label: 'Turn on surveys', achieved: ({ team }) => !!team.surveys_opt_in },
            {
                key: 'responses',
                label: 'Launch a survey and collect your first response',
                achieved: ({ signals }) => signals.surveyResponses > 0,
            },
        ],
        quality: [],
        stat: ({ signals }) => ({ value: signals.surveyResponses, label: 'responses · 30d' }),
    },
    [ProductKey.EXPERIMENTS]: {
        bestFor: 'A/B testing',
        docsUrl: 'https://posthog.com/docs/experiments',
        requiresEvents: true,
        activation: [
            installAnySdk,
            // Experiments require a feature flag: exposure rides on flag evaluations
            {
                key: 'flag_called',
                label: 'Call a feature flag from your code',
                achieved: ({ signals }) => signals.flagCalls > 0,
            },
        ],
        quality: [
            { ...firstCustomEvent, label: 'Track your goal metric with a custom event' },
            {
                key: 'prod_flag_calls',
                label: 'Run experiments on production traffic',
                achieved: ({ signals }) => signals.prodFlagCalls > 0,
            },
        ],
    },
    [ProductKey.AI_OBSERVABILITY]: {
        bestFor: 'LLM-powered apps',
        docsUrl: 'https://posthog.com/docs/llm-analytics',
        activation: [
            {
                key: 'server_sdk',
                label: 'Install a server SDK',
                achieved: ({ signals }) => signals.backendEvents > 0,
            },
            {
                key: 'ai_events',
                label: 'Wrap your LLM calls to capture generations',
                achieved: ({ signals }) => signals.aiGenerations + signals.aiTraceEvents > 0,
            },
        ],
        quality: [
            {
                key: 'traces',
                label: 'Capture full traces, not just generations',
                achieved: ({ signals }) => signals.aiTraceEvents > 0,
            },
        ],
        stat: ({ signals }) => ({
            value: signals.aiGenerations + signals.aiTraceEvents,
            label: 'AI events · 30d',
        }),
    },
    [ProductKey.DATA_WAREHOUSE]: {
        bestFor: 'joining external data',
        docsUrl: 'https://posthog.com/docs/data-warehouse',
        usableByDefault: true,
        activation: [
            {
                key: 'first_source',
                label: 'Connect your first source',
                achieved: ({ resources }) => (resources.sourcesCount ?? 0) > 0,
            },
        ],
        quality: [
            {
                key: 'second_source',
                label: 'Connect a second source to join across systems',
                achieved: ({ resources }) => (resources.sourcesCount ?? 0) >= 2,
            },
        ],
        stat: ({ resources }) => ({ value: resources.sourcesCount ?? 0, label: 'sources connected' }),
    },
    [ProductKey.WORKFLOWS]: {
        bestFor: 'automations & messaging',
        description: 'Automate messages and actions. No install needed, though it works best with events flowing.',
        usableByDefault: true,
        activation: [
            {
                key: 'first_workflow',
                label: 'Create your first workflow',
                achieved: ({ resources }) => (resources.workflowsCount ?? 0) > 0,
            },
        ],
        quality: [
            {
                key: 'event_trigger',
                label: 'Trigger a workflow from an event',
                achieved: ({ resources }) => (resources.eventTriggeredWorkflows ?? 0) > 0,
            },
            { ...firstCustomEvent, label: 'Capture custom events for smarter triggers' },
        ],
        stat: ({ resources }) => ({ value: resources.workflowsCount ?? 0, label: 'workflows' }),
    },
    [ProductKey.LOGS]: {
        bestFor: 'backend debugging',
        docsUrl: 'https://posthog.com/docs/logs',
        activation: [
            {
                key: 'logs_flowing',
                label: 'Point your OpenTelemetry logs at PostHog',
                achieved: ({ resources }) => resources.hasLogs === true,
            },
        ],
        quality: [],
    },
    [ProductKey.MCP_ANALYTICS]: {
        bestFor: 'MCP server owners',
        activation: [
            {
                key: 'instrumented',
                label: 'Instrument your MCP server',
                achieved: ({ signals }) => signals.mcpInitialize > 0 || signals.mcpToolCalls > 0,
            },
            {
                key: 'tool_calls',
                label: 'See real tool calls come in',
                achieved: ({ signals }) => signals.mcpToolCalls > 0,
            },
        ],
        quality: [
            {
                // The product's own dashboard graduates to its metrics view around this volume
                key: 'volume',
                label: 'Reach 300 tool calls to unlock usage metrics',
                achieved: ({ signals }) => signals.mcpToolCalls >= 300,
            },
        ],
        stat: ({ signals }) => ({ value: signals.mcpToolCalls, label: 'tool calls · 30d' }),
    },
    [ProductKey.CONVERSATIONS]: {
        bestFor: 'customer support',
        // Admin-gated team field: the enable listener explains the permission on a 403
        optInPayload: { conversations_enabled: true },
        enabled: (team) => !!team.conversations_enabled,
        activation: [
            {
                key: 'enabled',
                label: 'Turn on Support',
                achieved: ({ team }) => !!team.conversations_enabled,
            },
            {
                key: 'first_ticket',
                label: 'Connect a channel and receive your first ticket',
                achieved: ({ resources }) => (resources.ticketsCount ?? 0) > 0,
            },
        ],
        quality: [],
        stat: ({ resources }) => ({ value: resources.ticketsCount ?? 0, label: 'tickets' }),
    },
}

const isFullTeam = (team: TeamType | TeamPublicType | null): team is TeamType =>
    !!team && 'has_completed_onboarding_for' in team

// The scene is many users' homepage, so it can remount on every "Home" click. The signals
// query aggregates 30 days of events — too expensive to re-run per mount, and statuses
// don't need to be fresher than a few minutes.
const ACTIVATION_DATA_CACHE_TTL_MS = 5 * 60 * 1000
let activationDataCache: { teamId: number; fetchedAt: number; data: QuickstartActivationData } | null = null

function buildProduct(key: ProductKey, ctx: StatusContext): QuickstartProduct | null {
    const definition = QUICKSTART_PRODUCT_DEFINITIONS[key]
    const meta = (availableOnboardingProducts as Partial<Record<ProductKey, OnboardingProduct>>)[key]
    if (!definition || !meta) {
        return null
    }
    return {
        key,
        name: toSentenceCase(meta.name),
        description: definition.description ?? meta.userCentricDescription ?? meta.description,
        icon: meta.icon,
        iconColor: meta.iconColor,
        bestFor: definition.bestFor,
        status: deriveToolStatus(definition, ctx),
        requiresEvents: !!definition.requiresEvents,
        url: meta.url,
        setupUrl: urls.onboarding({ productKey: key }),
        docsUrl: definition.docsUrl,
    }
}

export const quickstartLogic = kea<quickstartLogicType>([
    path(['scenes', 'quickstart', 'quickstartLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        enableProduct: (productKey: ProductKey) => ({ productKey }),
        productEnableFinished: (productKey: ProductKey) => ({ productKey }),
        openToolSetupModal: (productKey: ProductKey) => ({ productKey }),
        closeToolSetupModal: true,
        setPublicationsHasMore: (feed: PublicationFeedKey, hasMore: boolean) => ({ feed, hasMore }),
    }),
    loaders(({ actions, values }) => {
        // Swallow errors: without data the rail simply doesn't render, and a feed
        // hiccup must never toast at a brand-new user.
        const loadFeedPage = async (
            feed: PublicationFeedKey,
            current: QuickstartPublication[]
        ): Promise<QuickstartPublication[]> => {
            if (current.length > 0 && !values.publicationsHasMore[feed]) {
                return current
            }
            try {
                const page = await fetchPublicationsPage(feed, current.length)
                actions.setPublicationsHasMore(feed, page.hasMore)
                if (current.length === 0) {
                    return page.publications
                }
                // The feed can shift between pages (a new post lands), so drop
                // anything already shown instead of rendering duplicate cards
                const seen = new Set(current.map((publication) => publication.url))
                const merged = [...current, ...page.publications.filter((publication) => !seen.has(publication.url))]
                posthog.capture('quickstart publications loaded more', { feed, total: merged.length })
                return merged
            } catch {
                actions.setPublicationsHasMore(feed, false)
                return current
            }
        }
        return {
            activationData: [
                { signals: null, resources: EMPTY_RESOURCES } as QuickstartActivationData,
                {
                    // Every sub-fetch is best-effort: a failure leaves its facts null and the
                    // affected rungs simply read as unachieved
                    loadActivationData: async (): Promise<QuickstartActivationData> => {
                        const teamId = values.currentTeam?.id
                        const cached = activationDataCache
                        if (
                            teamId &&
                            cached &&
                            cached.teamId === teamId &&
                            Date.now() - cached.fetchedAt < ACTIVATION_DATA_CACHE_TTL_MS
                        ) {
                            return cached.data
                        }

                        const queryTags = { scene: 'Quickstart', productKey: 'platform_and_support' } as const
                        // Approximates posthog/models/team/production_event_activation.py: hostless
                        // events count as production only when they come from a server SDK, and
                        // dev hosts include tunnels and reserved TLDs, not just localhost
                        const signalsQuery = hogql`
                            SELECT
                                count() AS total_events,
                                countIf(is_prod) AS prod_events,
                                countIf(is_custom) AS custom_events,
                                uniqIf(event, is_custom) AS distinct_custom_events,
                                countIf(event = '$identify') AS identify_calls,
                                countIf(event = '$exception') AS exceptions,
                                countIf(event = '$exception' AND is_backend) AS server_exceptions,
                                countIf(is_backend) AS backend_events,
                                countIf(event = '$feature_flag_called') AS flag_calls,
                                countIf(event = '$feature_flag_called' AND is_prod) AS prod_flag_calls,
                                countIf(event = '$pageview') AS pageviews,
                                countIf(event = '$pageview' AND is_prod) AS prod_pageviews,
                                countIf(event = 'survey sent') AS survey_responses,
                                countIf(event = '$ai_generation') AS ai_generations,
                                countIf(event IN ('$ai_trace', '$ai_span', '$ai_embedding')) AS ai_trace_events,
                                countIf(event = '$mcp_initialize') AS mcp_initialize,
                                countIf(event = '$mcp_tool_call') AS mcp_tool_calls
                            FROM (
                                SELECT
                                    event,
                                    properties.$lib IN ('posthog-node', 'posthog-python', 'posthog-go', 'posthog-ruby', 'posthog-php', 'posthog-java', 'posthog-dotnet', 'posthog-elixir', 'posthog-rs') AS is_backend,
                                    event NOT LIKE '$%' AND event NOT IN ('survey sent', 'survey shown', 'survey dismissed') AS is_custom,
                                    if(
                                        properties.$host IS NULL,
                                        properties.$lib IN ('posthog-node', 'posthog-python', 'posthog-go', 'posthog-ruby', 'posthog-php', 'posthog-java', 'posthog-dotnet', 'posthog-elixir', 'posthog-rs'),
                                        NOT (
                                            properties.$host LIKE 'localhost%'
                                            OR properties.$host LIKE '127.0.0.1%'
                                            OR properties.$host LIKE '0.0.0.0%'
                                            OR properties.$host LIKE '192.168.%'
                                            OR properties.$host LIKE '%.local'
                                            OR properties.$host LIKE '%.local:%'
                                            OR properties.$host LIKE '%.test'
                                            OR properties.$host LIKE '%.test:%'
                                            OR properties.$host LIKE '%.internal'
                                            OR properties.$host LIKE '%.internal:%'
                                            OR properties.$host LIKE '%.example'
                                            OR properties.$host LIKE '%.example:%'
                                            OR properties.$host LIKE '%.ngrok%'
                                            OR properties.$host LIKE '%.nip.io%'
                                            OR properties.$host LIKE '%.ts.net%'
                                            OR properties.$host LIKE '%.trycloudflare.com%'
                                            OR properties.$host LIKE '%.loca.lt%'
                                        )
                                    ) AS is_prod
                                FROM events
                                WHERE timestamp >= now() - INTERVAL 30 DAY AND timestamp <= now()
                            )`
                        const replayQuery = hogql`
                            SELECT count(DISTINCT session_id)
                            FROM raw_session_replay_events
                            WHERE min_first_timestamp >= now() - INTERVAL 30 DAY`

                        const [
                            signalsResult,
                            replayResult,
                            hasLogsResult,
                            sourcesResult,
                            flowsResult,
                            symbolSetsResult,
                            alertsResult,
                            ticketsResult,
                        ] = await Promise.allSettled([
                            api.queryHogQL(signalsQuery, queryTags),
                            api.queryHogQL(replayQuery, queryTags),
                            api.logs.hasLogs(),
                            api.externalDataSources.list(),
                            api.hogFlows.getHogFlows(),
                            api.errorTracking.symbolSets.list({ offset: 0, limit: 1 }),
                            api.hogFunctions.list({
                                types: ['destination'],
                                filter_groups: ERROR_TRACKING_ALERT_FILTERS,
                                limit: 1,
                            }),
                            api.conversationsTickets.list({ limit: 1 }),
                        ])

                        let signals: QuickstartToolSignals | null = null
                        if (signalsResult.status === 'fulfilled') {
                            const row = signalsResult.value.results?.[0]
                            if (row) {
                                signals = {
                                    totalEvents: Number(row[0]) || 0,
                                    prodEvents: Number(row[1]) || 0,
                                    customEvents: Number(row[2]) || 0,
                                    distinctCustomEvents: Number(row[3]) || 0,
                                    identifyCalls: Number(row[4]) || 0,
                                    exceptions: Number(row[5]) || 0,
                                    serverExceptions: Number(row[6]) || 0,
                                    backendEvents: Number(row[7]) || 0,
                                    flagCalls: Number(row[8]) || 0,
                                    prodFlagCalls: Number(row[9]) || 0,
                                    pageviews: Number(row[10]) || 0,
                                    prodPageviews: Number(row[11]) || 0,
                                    surveyResponses: Number(row[12]) || 0,
                                    aiGenerations: Number(row[13]) || 0,
                                    aiTraceEvents: Number(row[14]) || 0,
                                    mcpInitialize: Number(row[15]) || 0,
                                    mcpToolCalls: Number(row[16]) || 0,
                                }
                            }
                        }

                        const workflows = flowsResult.status === 'fulfilled' ? flowsResult.value.results : null
                        const activeWorkflows = workflows?.filter((flow) => flow.status !== 'archived') ?? null
                        const resources: QuickstartResources = {
                            replayRecordings:
                                replayResult.status === 'fulfilled'
                                    ? Number(replayResult.value.results?.[0]?.[0]) || 0
                                    : null,
                            hasLogs: hasLogsResult.status === 'fulfilled' ? hasLogsResult.value : null,
                            sourcesCount:
                                sourcesResult.status === 'fulfilled'
                                    ? (sourcesResult.value.results?.length ?? 0)
                                    : null,
                            workflowsCount: activeWorkflows ? activeWorkflows.length : null,
                            eventTriggeredWorkflows: activeWorkflows
                                ? activeWorkflows.filter((flow) => flow.trigger?.type === 'event').length
                                : null,
                            symbolSetsCount:
                                symbolSetsResult.status === 'fulfilled'
                                    ? (symbolSetsResult.value.count ?? symbolSetsResult.value.results?.length ?? 0)
                                    : null,
                            errorAlertsCount:
                                alertsResult.status === 'fulfilled'
                                    ? (alertsResult.value.count ?? alertsResult.value.results?.length ?? 0)
                                    : null,
                            ticketsCount:
                                ticketsResult.status === 'fulfilled'
                                    ? (ticketsResult.value.count ?? ticketsResult.value.results?.length ?? 0)
                                    : null,
                        }

                        const data: QuickstartActivationData = { signals, resources }
                        if (teamId) {
                            activationDataCache = { teamId, fetchedAt: Date.now(), data }
                        }
                        return data
                    },
                },
            ],
            blogPublications: [
                [] as QuickstartPublication[],
                {
                    loadBlogPublications: async (): Promise<QuickstartPublication[]> => await loadFeedPage('blog', []),
                    loadMoreBlogPublications: async (): Promise<QuickstartPublication[]> =>
                        await loadFeedPage('blog', values.blogPublications),
                },
            ],
            newsletterPublications: [
                [] as QuickstartPublication[],
                {
                    loadNewsletterPublications: async (): Promise<QuickstartPublication[]> =>
                        await loadFeedPage('newsletter', []),
                    loadMoreNewsletterPublications: async (): Promise<QuickstartPublication[]> =>
                        await loadFeedPage('newsletter', values.newsletterPublications),
                },
            ],
        }
    }),
    reducers({
        enablingProducts: [
            {} as Record<string, boolean>,
            {
                enableProduct: (state, { productKey }) => ({ ...state, [productKey]: true }),
                productEnableFinished: (state, { productKey }) => {
                    const { [productKey]: _, ...rest } = state
                    return rest
                },
            },
        ],
        publicationsHasMore: [
            { blog: true, newsletter: true } as Record<PublicationFeedKey, boolean>,
            {
                setPublicationsHasMore: (state, { feed, hasMore }) => ({ ...state, [feed]: hasMore }),
            },
        ],
        setupModalProductKey: [
            null as ProductKey | null,
            {
                openToolSetupModal: (_, { productKey }) => productKey,
                closeToolSetupModal: () => null,
            },
        ],
    }),
    selectors({
        hasIngestedEvent: [(s) => [s.currentTeam], (currentTeam): boolean => !!currentTeam?.ingested_event],
        products: [
            (s) => [s.currentTeam, s.activationData],
            (currentTeam, activationData): QuickstartProduct[] => {
                if (!isFullTeam(currentTeam)) {
                    return []
                }
                const ctx: StatusContext = {
                    team: currentTeam,
                    signals: activationData.signals ?? EMPTY_TOOL_SIGNALS,
                    resources: activationData.resources,
                }
                return QUICKSTART_PRODUCT_ORDER.map((key) => buildProduct(key, ctx)).filter(
                    (product): product is QuickstartProduct => product !== null
                )
            },
        ],
        activeProductCount: [
            (s) => [s.products],
            (products): number => products.filter((product) => product.status.level === 'live').length,
        ],
        totalProductCount: [(s) => [s.products], (products): number => products.length],
        setupModalProduct: [
            (s) => [s.setupModalProductKey, s.products],
            (setupModalProductKey, products): QuickstartProduct | null =>
                (setupModalProductKey && products.find((product) => product.key === setupModalProductKey)) || null,
        ],
    }),
    listeners(({ actions, values }) => ({
        enableProduct: async ({ productKey }) => {
            const definition = QUICKSTART_PRODUCT_DEFINITIONS[productKey]
            if (!definition?.optInPayload) {
                actions.productEnableFinished(productKey)
                return
            }
            try {
                await teamLogic.asyncActions.updateCurrentTeam(definition.optInPayload)
            } catch (error) {
                // The opt-in didn't apply, so don't record an enable that never happened.
                // Some team fields (e.g. conversations_enabled) are admin-only.
                const status = (error as { status?: number } | null)?.status
                lemonToast.error(
                    status === 403
                        ? 'Only project admins can turn this on. Ask an admin to enable it.'
                        : "Couldn't enable it. Please try again."
                )
                return
            } finally {
                actions.productEnableFinished(productKey)
            }
            posthog.capture('quickstart product enabled', { product_key: productKey })
            void addProductIntent({
                product_type: productKey,
                intent_context: ProductIntentContext.QUICK_START_PRODUCT_SELECTED,
            })
        },
        // Fires after signals settle so the payload reflects real data, not the empty fallback
        loadActivationDataSuccess: () => {
            posthog.capture('quickstart viewed', {
                has_ingested_event: values.hasIngestedEvent,
                live_products: values.products.filter((product) => product.status.level === 'live').map((p) => p.key),
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadActivationData()
        actions.loadBlogPublications()
        actions.loadNewsletterPublications()
    }),
])
