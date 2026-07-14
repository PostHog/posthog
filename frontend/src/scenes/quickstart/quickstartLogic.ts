import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { addProductIntent } from 'lib/utils/product-intents'
import { availableOnboardingProducts, toSentenceCase } from 'scenes/onboarding/shared/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import type { OnboardingProduct, TeamPublicType, TeamType } from '~/types'

import { QuickstartPublication, fetchQuickstartPublications } from './publications'
import type { quickstartLogicType } from './quickstartLogicType'

export type QuickstartProductStatus = 'active' | 'ready' | 'needs_setup'

export interface QuickstartProduct {
    key: ProductKey
    name: string
    description: string
    icon: string
    iconColor: string
    /** Short audience hint rendered as "Best for …" on the card */
    bestFor: string
    status: QuickstartProductStatus
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
    /** Team settings patched to turn the product on in one click. Absent means the product needs a setup flow. */
    optInPayload?: Partial<TeamType>
    isActive: (team: TeamType) => boolean
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
        isActive: (team) => team.ingested_event || hasOnboarded(team, ProductKey.PRODUCT_ANALYTICS),
    },
    [ProductKey.WEB_ANALYTICS]: {
        bestFor: 'marketing & traffic',
        docsUrl: 'https://posthog.com/docs/web-analytics',
        // Web analytics runs off autocaptured pageviews, so it's live as soon as events flow
        isActive: (team) => team.ingested_event || hasOnboarded(team, ProductKey.WEB_ANALYTICS),
    },
    [ProductKey.SESSION_REPLAY]: {
        bestFor: 'debugging UX issues',
        docsUrl: 'https://posthog.com/docs/session-replay',
        // Same payload the replay onboarding step applies
        optInPayload: {
            session_recording_opt_in: true,
            capture_console_log_opt_in: true,
            capture_performance_opt_in: true,
        },
        isActive: (team) => !!team.session_recording_opt_in,
    },
    [ProductKey.ERROR_TRACKING]: {
        bestFor: 'catching bugs early',
        docsUrl: 'https://posthog.com/docs/error-tracking',
        optInPayload: { autocapture_exceptions_opt_in: true },
        isActive: (team) => !!team.autocapture_exceptions_opt_in,
    },
    [ProductKey.FEATURE_FLAGS]: {
        bestFor: 'safe rollouts',
        docsUrl: 'https://posthog.com/docs/feature-flags',
        isActive: (team) => hasOnboarded(team, ProductKey.FEATURE_FLAGS),
    },
    [ProductKey.SURVEYS]: {
        bestFor: 'user feedback',
        docsUrl: 'https://posthog.com/docs/surveys',
        optInPayload: { surveys_opt_in: true },
        isActive: (team) => !!team.surveys_opt_in,
    },
    [ProductKey.EXPERIMENTS]: {
        bestFor: 'A/B testing',
        docsUrl: 'https://posthog.com/docs/experiments',
        isActive: (team) => hasOnboarded(team, ProductKey.EXPERIMENTS),
    },
    [ProductKey.AI_OBSERVABILITY]: {
        bestFor: 'LLM-powered apps',
        docsUrl: 'https://posthog.com/docs/llm-analytics',
        isActive: (team) => hasOnboarded(team, ProductKey.AI_OBSERVABILITY),
    },
    [ProductKey.DATA_WAREHOUSE]: {
        bestFor: 'joining external data',
        docsUrl: 'https://posthog.com/docs/data-warehouse',
        isActive: (team) => hasOnboarded(team, ProductKey.DATA_WAREHOUSE),
    },
    [ProductKey.WORKFLOWS]: {
        bestFor: 'automations & messaging',
        isActive: (team) => hasOnboarded(team, ProductKey.WORKFLOWS),
    },
    [ProductKey.LOGS]: {
        bestFor: 'backend debugging',
        docsUrl: 'https://posthog.com/docs/logs',
        isActive: (team) => hasOnboarded(team, ProductKey.LOGS),
    },
    [ProductKey.MCP_ANALYTICS]: {
        bestFor: 'MCP server owners',
        isActive: (team) => hasOnboarded(team, ProductKey.MCP_ANALYTICS),
    },
    [ProductKey.CONVERSATIONS]: {
        bestFor: 'customer support',
        optInPayload: { conversations_enabled: true },
        isActive: (team) => !!team.conversations_enabled,
    },
}

const isFullTeam = (team: TeamType | TeamPublicType | null): team is TeamType =>
    !!team && 'has_completed_onboarding_for' in team

function buildProduct(key: ProductKey, featured: boolean, team: TeamType): QuickstartProduct | null {
    const definition = QUICKSTART_PRODUCT_DEFINITIONS[key]
    const meta = (availableOnboardingProducts as Partial<Record<ProductKey, OnboardingProduct>>)[key]
    if (!definition || !meta) {
        return null
    }
    const status: QuickstartProductStatus = definition.isActive(team)
        ? 'active'
        : definition.optInPayload
          ? 'ready'
          : 'needs_setup'
    return {
        key,
        featured,
        name: toSentenceCase(meta.name),
        description: meta.userCentricDescription ?? meta.description,
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
        actions: [teamLogic, ['updateCurrentTeam', 'updateCurrentTeamSuccess', 'updateCurrentTeamFailure']],
    })),
    actions({
        enableProduct: (productKey: ProductKey) => ({ productKey }),
    }),
    loaders({
        publications: [
            [] as QuickstartPublication[],
            {
                // Swallow errors: without data the section simply doesn't render,
                // and a feed hiccup must never toast at a brand-new user.
                loadPublications: async (): Promise<QuickstartPublication[]> => {
                    try {
                        return await fetchQuickstartPublications()
                    } catch {
                        return []
                    }
                },
            },
        ],
    }),
    reducers({
        enablingProducts: [
            {} as Record<string, boolean>,
            {
                enableProduct: (state, { productKey }) => ({ ...state, [productKey]: true }),
                updateCurrentTeamSuccess: () => ({}),
                updateCurrentTeamFailure: () => ({}),
            },
        ],
    }),
    selectors({
        hasIngestedEvent: [(s) => [s.currentTeam], (currentTeam): boolean => !!currentTeam?.ingested_event],
        products: [
            (s) => [s.currentTeam],
            (currentTeam): QuickstartProduct[] => {
                if (!isFullTeam(currentTeam)) {
                    return []
                }
                return [
                    ...QUICKSTART_FEATURED_PRODUCTS.map((key) => buildProduct(key, true, currentTeam)),
                    ...QUICKSTART_MORE_PRODUCTS.map((key) => buildProduct(key, false, currentTeam)),
                ].filter((product): product is QuickstartProduct => product !== null)
            },
        ],
        featuredProducts: [
            (s) => [s.products],
            (products): QuickstartProduct[] => products.filter((product) => product.featured),
        ],
        moreProducts: [
            (s) => [s.products],
            (products): QuickstartProduct[] => products.filter((product) => !product.featured),
        ],
    }),
    listeners(({ actions }) => ({
        enableProduct: ({ productKey }) => {
            const definition = QUICKSTART_PRODUCT_DEFINITIONS[productKey]
            if (!definition?.optInPayload) {
                return
            }
            posthog.capture('quickstart product enabled', { product_key: productKey })
            void addProductIntent({
                product_type: productKey,
                intent_context: ProductIntentContext.QUICK_START_PRODUCT_SELECTED,
            })
            actions.updateCurrentTeam(definition.optInPayload)
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadPublications()
        posthog.capture('quickstart viewed', {
            has_ingested_event: values.hasIngestedEvent,
            active_products: values.products.filter((product) => product.status === 'active').map((p) => p.key),
        })
    }),
])
