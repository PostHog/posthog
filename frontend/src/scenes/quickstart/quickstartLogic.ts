import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { addProductIntent } from 'lib/utils/product-intents'
import { availableOnboardingProducts, toSentenceCase } from 'scenes/onboarding/shared/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import type { OnboardingProduct, TeamPublicType, TeamType } from '~/types'

import { PublicationFeedKey, QuickstartPublication, fetchPublicationsPage } from './publications'
import type { quickstartLogicType } from './quickstartLogicType'

export type QuickstartProductStatus = 'active' | 'ready' | 'enableable' | 'needs_install' | 'needs_setup'

/** Event-derived proof-of-life counters for the last 30 days */
export interface QuickstartToolSignals {
    totalEvents: number
    prodEvents: number
    customEvents: number
    exceptions: number
    backendEvents: number
    flagCalls: number
    pageviews: number
    surveyResponses: number
    aiGenerations: number
}

const EMPTY_TOOL_SIGNALS: QuickstartToolSignals = {
    totalEvents: 0,
    prodEvents: 0,
    customEvents: 0,
    exceptions: 0,
    backendEvents: 0,
    flagCalls: 0,
    pageviews: 0,
    surveyResponses: 0,
    aiGenerations: 0,
}

export interface QuickstartProduct {
    key: ProductKey
    name: string
    description: string
    icon: string
    iconColor: string
    /** Short audience hint rendered as "Best for …" on the card */
    bestFor: string
    status: QuickstartProductStatus
    /** Nudge toward the next signal worth chasing, shown on the card */
    signalHint?: string
    /** Where "Open" points once the product is in use */
    url: string
    /** Where "Set up" points when the product needs an install step */
    setupUrl: string
    docsUrl?: string
    featured: boolean
}

interface QuickstartProductDefinition {
    bestFor: string
    docsUrl?: string
    /** Overrides the onboarding metadata copy when the quickstart card needs different framing */
    description?: string
    /** Team settings patched to turn the product on in one click. Absent means the product needs a setup flow. */
    optInPayload?: Partial<TeamType>
    /** The tool is pointless without SDK events, so it asks for an install before anything else */
    requiresEvents?: boolean
    /** Proof the tool is delivering value. Without it, being usable is enough to count as active. */
    hasSignal?: (signals: QuickstartToolSignals) => boolean
    /** Whether setup or enablement is done, independent of any signal */
    isUsable: (team: TeamType) => boolean
    /** Nudge toward the next signal, shown while the tool is ready or active */
    getSignalHint?: (signals: QuickstartToolSignals) => string | null
}

function deriveStatus(
    definition: QuickstartProductDefinition,
    team: TeamType,
    signals: QuickstartToolSignals
): QuickstartProductStatus {
    if (definition.requiresEvents && !team.ingested_event) {
        return 'needs_install'
    }
    // A signal always wins: exceptions from a server SDK count even if the frontend opt-in is off
    if (definition.hasSignal?.(signals)) {
        return 'active'
    }
    if (definition.optInPayload && !definition.isUsable(team)) {
        return 'enableable'
    }
    if (!definition.isUsable(team)) {
        return 'needs_setup'
    }
    return definition.hasSignal ? 'ready' : 'active'
}

const hasOnboarded = (team: TeamType, key: ProductKey): boolean => !!team.has_completed_onboarding_for?.[key]

/** The five products every new project should see first. Order is display order. */
export const QUICKSTART_FEATURED_PRODUCTS: ProductKey[] = [
    ProductKey.PRODUCT_ANALYTICS,
    ProductKey.WEB_ANALYTICS,
    ProductKey.SESSION_REPLAY,
    ProductKey.ERROR_TRACKING,
    ProductKey.FEATURE_FLAGS,
]

export const QUICKSTART_MORE_PRODUCTS: ProductKey[] = [
    ProductKey.SURVEYS,
    ProductKey.EXPERIMENTS,
    ProductKey.AI_OBSERVABILITY,
    ProductKey.DATA_WAREHOUSE,
    ProductKey.WORKFLOWS,
    ProductKey.LOGS,
    ProductKey.MCP_ANALYTICS,
    ProductKey.CONVERSATIONS,
]

const QUICKSTART_PRODUCT_DEFINITIONS: Partial<Record<ProductKey, QuickstartProductDefinition>> = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        bestFor: 'understanding user behavior',
        docsUrl: 'https://posthog.com/docs/product-analytics',
        requiresEvents: true,
        isUsable: () => true,
        hasSignal: (signals) => signals.totalEvents > 0,
        getSignalHint: (signals) =>
            signals.totalEvents > 0 && signals.customEvents === 0
                ? 'Autocapture only so far. Add custom events for deeper insights.'
                : null,
    },
    [ProductKey.WEB_ANALYTICS]: {
        bestFor: 'marketing & traffic',
        docsUrl: 'https://posthog.com/docs/web-analytics',
        requiresEvents: true,
        isUsable: () => true,
        // Web analytics runs off autocaptured pageviews, so it's live as soon as they flow
        hasSignal: (signals) => signals.pageviews > 0,
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
        isUsable: (team) => !!team.session_recording_opt_in,
    },
    [ProductKey.ERROR_TRACKING]: {
        bestFor: 'catching bugs early',
        docsUrl: 'https://posthog.com/docs/error-tracking',
        requiresEvents: true,
        optInPayload: { autocapture_exceptions_opt_in: true },
        isUsable: (team) => !!team.autocapture_exceptions_opt_in,
        hasSignal: (signals) => signals.exceptions > 0,
        getSignalHint: (signals) =>
            signals.exceptions === 0
                ? 'No exceptions captured yet. They show up here the moment your code throws.'
                : signals.backendEvents === 0
                  ? 'Frontend only so far. Add a server SDK to catch backend errors too.'
                  : null,
    },
    [ProductKey.FEATURE_FLAGS]: {
        bestFor: 'safe rollouts',
        docsUrl: 'https://posthog.com/docs/feature-flags',
        requiresEvents: true,
        isUsable: () => true,
        hasSignal: (signals) => signals.flagCalls > 0,
        getSignalHint: (signals) =>
            signals.flagCalls === 0 ? 'Create a flag, then check it from your code to see it evaluated here.' : null,
    },
    [ProductKey.SURVEYS]: {
        bestFor: 'user feedback',
        docsUrl: 'https://posthog.com/docs/surveys',
        requiresEvents: true,
        optInPayload: { surveys_opt_in: true },
        isUsable: (team) => !!team.surveys_opt_in,
        hasSignal: (signals) => signals.surveyResponses > 0,
        getSignalHint: (signals) =>
            signals.surveyResponses === 0 ? 'Launch your first survey to start collecting responses.' : null,
    },
    [ProductKey.EXPERIMENTS]: {
        bestFor: 'A/B testing',
        docsUrl: 'https://posthog.com/docs/experiments',
        requiresEvents: true,
        isUsable: () => true,
        // Experiments ride on feature flag evaluations from the SDK
        hasSignal: (signals) => signals.flagCalls > 0,
        getSignalHint: (signals) =>
            signals.flagCalls === 0 ? 'Experiments run on feature flags. Wire the SDK flag check first.' : null,
    },
    [ProductKey.AI_OBSERVABILITY]: {
        bestFor: 'LLM-powered apps',
        docsUrl: 'https://posthog.com/docs/llm-analytics',
        isUsable: () => true,
        hasSignal: (signals) => signals.aiGenerations > 0,
        getSignalHint: (signals) =>
            signals.aiGenerations === 0 ? 'Instrument your LLM calls to see traces, costs, and latency.' : null,
    },
    [ProductKey.DATA_WAREHOUSE]: {
        bestFor: 'joining external data',
        docsUrl: 'https://posthog.com/docs/data-warehouse',
        isUsable: (team) => hasOnboarded(team, ProductKey.DATA_WAREHOUSE),
    },
    [ProductKey.WORKFLOWS]: {
        bestFor: 'automations & messaging',
        description: 'Automate messages and actions. No install needed, though it works best with events flowing.',
        // Workflows run without any SDK install, so the tool is usable from day one
        isUsable: () => true,
        hasSignal: (signals) => signals.customEvents > 0,
        getSignalHint: (signals) =>
            signals.customEvents === 0 ? 'Works now. Custom events unlock smarter triggers.' : null,
    },
    [ProductKey.LOGS]: {
        bestFor: 'backend debugging',
        docsUrl: 'https://posthog.com/docs/logs',
        isUsable: (team) => hasOnboarded(team, ProductKey.LOGS),
    },
    [ProductKey.MCP_ANALYTICS]: {
        bestFor: 'MCP server owners',
        isUsable: (team) => hasOnboarded(team, ProductKey.MCP_ANALYTICS),
    },
    [ProductKey.CONVERSATIONS]: {
        bestFor: 'customer support',
        optInPayload: { conversations_enabled: true },
        isUsable: (team) => !!team.conversations_enabled,
    },
}

const isFullTeam = (team: TeamType | TeamPublicType | null): team is TeamType =>
    !!team && 'has_completed_onboarding_for' in team

// The scene is many users' homepage, so it can remount on every "Home" click. The signals
// query aggregates 30 days of events — too expensive to re-run per mount, and statuses
// don't need to be fresher than a few minutes.
const TOOL_SIGNALS_CACHE_TTL_MS = 5 * 60 * 1000
let toolSignalsCache: { teamId: number; fetchedAt: number; signals: QuickstartToolSignals | null } | null = null

function buildProduct(
    key: ProductKey,
    featured: boolean,
    team: TeamType,
    signals: QuickstartToolSignals
): QuickstartProduct | null {
    const definition = QUICKSTART_PRODUCT_DEFINITIONS[key]
    const meta = (availableOnboardingProducts as Partial<Record<ProductKey, OnboardingProduct>>)[key]
    if (!definition || !meta) {
        return null
    }
    const status = deriveStatus(definition, team, signals)
    const signalHint =
        status === 'ready' || status === 'active' ? (definition.getSignalHint?.(signals) ?? undefined) : undefined
    return {
        signalHint,
        key,
        featured,
        name: toSentenceCase(meta.name),
        description: definition.description ?? meta.userCentricDescription ?? meta.description,
        icon: meta.icon,
        iconColor: meta.iconColor,
        bestFor: definition.bestFor,
        status,
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
            toolSignals: [
                null as QuickstartToolSignals | null,
                {
                    // Errors leave signals null: statuses fall back to enablement-only semantics
                    loadToolSignals: async (): Promise<QuickstartToolSignals | null> => {
                        const teamId = values.currentTeam?.id
                        const cached = toolSignalsCache
                        if (
                            teamId &&
                            cached &&
                            cached.teamId === teamId &&
                            Date.now() - cached.fetchedAt < TOOL_SIGNALS_CACHE_TTL_MS
                        ) {
                            return cached.signals
                        }
                        try {
                            const query = hogql`
                                SELECT
                                    count() AS total_events,
                                    countIf(properties.$host IS NOT NULL AND NOT (
                                        properties.$host LIKE 'localhost%'
                                        OR properties.$host LIKE '127.0.0.1%'
                                        OR properties.$host LIKE '0.0.0.0%'
                                        OR properties.$host LIKE '%.local'
                                        OR properties.$host LIKE '%.local:%'
                                    )) AS prod_events,
                                    countIf(event NOT LIKE '$%' AND event NOT IN ('survey sent', 'survey shown', 'survey dismissed')) AS custom_events,
                                    countIf(event = '$exception') AS exceptions,
                                    countIf(properties.$lib IN ('posthog-node', 'posthog-python', 'posthog-go', 'posthog-ruby', 'posthog-php', 'posthog-java', 'posthog-dotnet', 'posthog-elixir')) AS backend_events,
                                    countIf(event = '$feature_flag_called') AS flag_calls,
                                    countIf(event = '$pageview') AS pageviews,
                                    countIf(event = 'survey sent') AS survey_responses,
                                    countIf(event = '$ai_generation') AS ai_generations
                                FROM events
                                WHERE timestamp >= now() - INTERVAL 30 DAY AND timestamp <= now()`
                            const res = await api.queryHogQL(query, {
                                scene: 'Quickstart',
                                productKey: 'platform_and_support',
                            })
                            const row = res.results?.[0]
                            const signals: QuickstartToolSignals | null = row
                                ? {
                                      totalEvents: Number(row[0]) || 0,
                                      prodEvents: Number(row[1]) || 0,
                                      customEvents: Number(row[2]) || 0,
                                      exceptions: Number(row[3]) || 0,
                                      backendEvents: Number(row[4]) || 0,
                                      flagCalls: Number(row[5]) || 0,
                                      pageviews: Number(row[6]) || 0,
                                      surveyResponses: Number(row[7]) || 0,
                                      aiGenerations: Number(row[8]) || 0,
                                  }
                                : null
                            if (teamId) {
                                toolSignalsCache = { teamId, fetchedAt: Date.now(), signals }
                            }
                            return signals
                        } catch {
                            return null
                        }
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
            (s) => [s.currentTeam, s.toolSignals],
            (currentTeam, toolSignals): QuickstartProduct[] => {
                if (!isFullTeam(currentTeam)) {
                    return []
                }
                const signals = toolSignals ?? EMPTY_TOOL_SIGNALS
                return [
                    ...QUICKSTART_FEATURED_PRODUCTS.map((key) => buildProduct(key, true, currentTeam, signals)),
                    ...QUICKSTART_MORE_PRODUCTS.map((key) => buildProduct(key, false, currentTeam, signals)),
                ].filter((product): product is QuickstartProduct => product !== null)
            },
        ],
        featuredProducts: [
            (s) => [s.products],
            (products): QuickstartProduct[] => products.filter((product) => product.featured),
        ],
        activeProductCount: [
            (s) => [s.products],
            (products): number => products.filter((product) => product.status === 'active').length,
        ],
        totalProductCount: [(s) => [s.products], (products): number => products.length],
        moreProducts: [
            (s) => [s.products],
            (products): QuickstartProduct[] => products.filter((product) => !product.featured),
        ],
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
            } catch {
                // The opt-in didn't apply, so don't record an enable that never happened
                lemonToast.error("Couldn't enable it. Please try again.")
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
        // Fires after signals settle so active_products reflects real data, not the empty fallback
        loadToolSignalsSuccess: () => {
            posthog.capture('quickstart viewed', {
                has_ingested_event: values.hasIngestedEvent,
                active_products: values.products.filter((product) => product.status === 'active').map((p) => p.key),
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadToolSignals()
        actions.loadBlogPublications()
        actions.loadNewsletterPublications()
    }),
])
