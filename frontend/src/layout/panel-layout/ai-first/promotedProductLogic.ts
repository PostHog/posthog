import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAppContext } from 'lib/utils/getAppContext'

import type { promotedProductLogicType } from './promotedProductLogicType'

export type PromotedProductVariant = 'control' | 'control_b' | 'intent' | 'intent_plus'

/** Product the slot falls back to when an entry-showing variant resolves no onboarding product or override. */
export const FALLBACK_PRODUCT_KEY = 'dashboards'

/** True for variants that should render the promoted-product sidebar entry. */
export function variantShowsEntry(variant: PromotedProductVariant | null): boolean {
    return variant === 'intent' || variant === 'intent_plus'
}

/** True for variants that let the user override the promoted product via the configure modal. */
export function variantAllowsOverride(variant: PromotedProductVariant | null): boolean {
    return variant === 'intent_plus'
}

// localStorage keys are team-scoped: a single browser can be logged into multiple
// projects, and the promoted product for project A shouldn't leak into project B.
// `currentTeamId()` resolves the team from `getAppContext()` (always present after auth).
function currentTeamId(): number | null {
    const id = getAppContext()?.current_team?.id
    return typeof id === 'number' ? id : null
}

export function localStorageProductKey(teamId: number): string {
    return `posthog-promoted-product:${teamId}`
}

export function localStorageOverrideKey(teamId: number): string {
    return `posthog-promoted-product-override:${teamId}`
}

/**
 * Single source of truth for the promoted-product registry — one record per product.
 * `PRODUCT_KEY_TO_URL` and `PRODUCT_KEY_LABELS` below are derived from it so a
 * new product can't be added to one map without the other.
 *
 * Labels follow PostHog's sentence-case convention (CLAUDE.md) — proper-noun
 * acronyms (LLM, AI) stay capitalised, everything else is sentence case.
 */
interface PromotedProductInfo {
    url: string
    /** Display label shown in the sidebar entry and the configure modal. */
    label: string
}

const PRODUCT_REGISTRY: Record<string, PromotedProductInfo> = {
    dashboards: { url: '/dashboard', label: 'Dashboards' },
    product_analytics: { url: '/insights', label: 'Product analytics' },
    web_analytics: { url: '/web', label: 'Web analytics' },
    session_replay: { url: '/replay', label: 'Session replay' },
    llm_analytics: { url: '/ai-observability', label: 'LLM analytics' },
    error_tracking: { url: '/error_tracking', label: 'Error tracking' },
    feature_flags: { url: '/feature_flags', label: 'Feature flags' },
    experiments: { url: '/experiments', label: 'Experiments' },
    surveys: { url: '/surveys', label: 'Surveys' },
    logs: { url: '/logs', label: 'Logs' },
    data_warehouse: { url: '/data-warehouse', label: 'Data warehouse' },
    workflows: { url: '/workflows', label: 'Workflows' },
    marketing_analytics: { url: '/marketing', label: 'Marketing analytics' },
}

const PRODUCT_KEY_TO_URL: Record<string, string> = Object.fromEntries(
    Object.entries(PRODUCT_REGISTRY).map(([key, { url }]) => [key, url])
)

export const PRODUCT_KEY_LABELS: Record<string, string> = Object.fromEntries(
    Object.entries(PRODUCT_REGISTRY).map(([key, { label }]) => [key, label])
)

/** Selectable product keys for the configure modal, in registry order. */
export const PROMOTED_PRODUCT_KEYS: string[] = Object.keys(PRODUCT_REGISTRY)

export function labelForPromotedProductKey(productKey: string): string {
    return PRODUCT_KEY_LABELS[productKey] ?? productKey
}

export function urlForPromotedProductKey(productKey: string): string | null {
    return PRODUCT_KEY_TO_URL[productKey] ?? null
}

/** Returns the product key when it names a known promoted product, otherwise null. */
export function resolveProductKey(productKey: string | null | undefined): string | null {
    return productKey && productKey in PRODUCT_KEY_TO_URL ? productKey : null
}

function readLocalStorageString(key: string): string | null {
    try {
        return window.localStorage.getItem(key)
    } catch {
        return null
    }
}

function readPromotedProductFromStorage(): string | null {
    const teamId = currentTeamId()
    if (teamId === null) {
        return null
    }
    return readLocalStorageString(localStorageProductKey(teamId))
}

function readPromotedProductOverrideFromStorage(): string | null {
    const teamId = currentTeamId()
    if (teamId === null) {
        return null
    }
    return resolveProductKey(readLocalStorageString(localStorageOverrideKey(teamId)))
}

export const promotedProductLogic = kea<promotedProductLogicType>([
    path(['layout', 'panel-layout', 'ai-first', 'promotedProductLogic']),

    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),

    actions({
        setOverride: (productKey: string) => ({ productKey }),
        clearOverride: true,
        showConfigureModal: true,
        hideConfigureModal: true,
        trackPromotedProductClick: true,
        refreshIntentFromStorage: true,
        refreshOverrideFromStorage: true,
        setPendingProduct: (productKey: string) => ({ productKey }),
    }),

    reducers({
        isConfigureModalOpen: [
            false,
            {
                showConfigureModal: () => true,
                hideConfigureModal: () => false,
            },
        ],
        promotedProductIntent: [
            null as string | null,
            {
                refreshIntentFromStorage: () =>
                    readPromotedProductFromStorage() ?? getAppContext()?.promoted_product_intent ?? null,
            },
        ],
        override: [
            null as string | null,
            {
                setOverride: (_, { productKey }) => productKey,
                clearOverride: () => null,
                refreshOverrideFromStorage: () => readPromotedProductOverrideFromStorage(),
            },
        ],
        // Pending product for the configure modal. We can't initialise it from
        // `effectiveProductKey` here (reducer can't read selectors), so a listener on
        // `showConfigureModal` reseeds it from the current product every time the modal
        // opens — preventing stale state in the always-mounted modal in `GlobalModals`.
        pendingProduct: [
            FALLBACK_PRODUCT_KEY,
            {
                setPendingProduct: (_, { productKey }) => productKey,
            },
        ],
    }),

    selectors({
        variant: [
            (s) => [s.featureFlags],
            (featureFlags): PromotedProductVariant | null => {
                const raw = featureFlags[FEATURE_FLAGS.PROMOTED_PRODUCT]
                if (raw === 'control' || raw === 'control_b' || raw === 'intent' || raw === 'intent_plus') {
                    return raw
                }
                return null
            },
        ],
        effectiveProductKey: [
            (s) => [s.variant, s.promotedProductIntent, s.override],
            (variant, intent, override): string | null => {
                if (!variantShowsEntry(variant)) {
                    return null
                }
                if (variantAllowsOverride(variant) && override) {
                    return override
                }
                return resolveProductKey(intent) ?? FALLBACK_PRODUCT_KEY
            },
        ],
        shouldRenderEntry: [
            (s) => [s.variant, s.effectiveProductKey],
            (variant, productKey): boolean => variantShowsEntry(variant) && productKey !== null,
        ],
        shouldRenderCog: [(s) => [s.variant], (variant): boolean => variantAllowsOverride(variant)],
        // The product the slot shows with no override — onboarding intent, else the fallback.
        // Drives the "Reset to default (…)" label so the user sees what reset reverts to.
        defaultProductKey: [
            (s) => [s.promotedProductIntent],
            (intent): string => resolveProductKey(intent) ?? FALLBACK_PRODUCT_KEY,
        ],
    }),

    listeners(({ actions, values }) => ({
        setOverride: ({ productKey }) => {
            const teamId = currentTeamId()
            if (teamId !== null) {
                try {
                    window.localStorage.setItem(localStorageOverrideKey(teamId), productKey)
                } catch {
                    // ignore — override is best-effort persistence in localStorage
                }
            }
            posthog.capture('promoted product config changed', {
                variant: values.variant,
                from: values.promotedProductIntent,
                to: productKey,
            })
        },
        clearOverride: () => {
            const teamId = currentTeamId()
            if (teamId !== null) {
                try {
                    window.localStorage.removeItem(localStorageOverrideKey(teamId))
                } catch {
                    // ignore
                }
            }
            posthog.capture('promoted product config changed', {
                variant: values.variant,
                from: values.promotedProductIntent,
                to: null,
            })
        },
        showConfigureModal: () => {
            // Seed the pending product from the current effectiveProductKey so the modal
            // always opens reflecting the user's current promoted product, even after
            // Reset-to-default or a fresh page load.
            const productKey = values.effectiveProductKey ?? FALLBACK_PRODUCT_KEY
            actions.setPendingProduct(productKey)
            posthog.capture('promoted product config opened', {
                variant: values.variant,
                current_product: productKey,
            })
        },
        trackPromotedProductClick: () => {
            const productKey = values.effectiveProductKey
            if (!productKey) {
                return
            }
            posthog.capture('promoted product clicked', {
                variant: values.variant,
                product_key: productKey,
            })
        },
    })),

    afterMount(({ actions }) => {
        actions.refreshIntentFromStorage()
        actions.refreshOverrideFromStorage()
    }),
])
