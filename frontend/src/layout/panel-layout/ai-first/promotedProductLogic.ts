import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAppContext } from 'lib/utils/getAppContext'

import type { promotedProductLogicType } from './promotedProductLogicType'

export type PromotedProductVariant = 'control' | 'control_b' | 'intent' | 'intent_plus'

export type PromotedProductTargetKind = 'product' | 'url'

export interface PromotedProductTarget {
    kind: PromotedProductTargetKind
    /** product key when kind === 'product', URL when kind === 'url'. */
    value: string
}

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

export function labelForPromotedProductKey(productKey: string): string {
    return PRODUCT_KEY_LABELS[productKey] ?? productKey
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

function readPromotedProductOverrideFromStorage(): PromotedProductTarget | null {
    const teamId = currentTeamId()
    if (teamId === null) {
        return null
    }
    const raw = readLocalStorageString(localStorageOverrideKey(teamId))
    if (!raw) {
        return null
    }
    try {
        const parsed = JSON.parse(raw) as PromotedProductTarget
        if (parsed && typeof parsed.value === 'string' && (parsed.kind === 'product' || parsed.kind === 'url')) {
            return parsed
        }
    } catch {
        // fall through
    }
    return null
}

function resolveProductTarget(productKey: string | null | undefined): PromotedProductTarget | null {
    if (!productKey) {
        return null
    }
    if (!(productKey in PRODUCT_KEY_TO_URL)) {
        return null
    }
    return { kind: 'product', value: productKey }
}

export const promotedProductLogic = kea<promotedProductLogicType>([
    path(['layout', 'panel-layout', 'ai-first', 'promotedProductLogic']),

    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),

    actions({
        setOverride: (override: PromotedProductTarget) => ({ override }),
        clearOverride: true,
        showConfigureModal: true,
        hideConfigureModal: true,
        trackPromotedProductClick: true,
        refreshIntentFromStorage: true,
        refreshOverrideFromStorage: true,
        setPendingKind: (kind: PromotedProductTargetKind) => ({ kind }),
        setPendingProduct: (productKey: string) => ({ productKey }),
        setPendingUrl: (url: string) => ({ url }),
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
            null as PromotedProductTarget | null,
            {
                setOverride: (_, { override }) => override,
                clearOverride: () => null,
                refreshOverrideFromStorage: () => readPromotedProductOverrideFromStorage(),
            },
        ],
        // Pending state for the configure modal. We can't initialise from
        // `effectiveTarget` here (reducer can't read selectors), so a listener
        // on `showConfigureModal` resets these from the current target every
        // time the modal opens — preventing stale state in the always-mounted
        // modal in `GlobalModals`.
        pendingKind: [
            'product' as PromotedProductTargetKind,
            {
                setPendingKind: (_, { kind }) => kind,
            },
        ],
        pendingProduct: [
            'product_analytics',
            {
                setPendingProduct: (_, { productKey }) => productKey,
            },
        ],
        pendingUrl: [
            '',
            {
                setPendingUrl: (_, { url }) => url,
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
        effectiveTarget: [
            (s) => [s.variant, s.promotedProductIntent, s.override],
            (variant, intent, override): PromotedProductTarget | null => {
                if (!variantShowsEntry(variant)) {
                    return null
                }
                if (variantAllowsOverride(variant) && override) {
                    return override
                }
                return resolveProductTarget(intent)
            },
        ],
        shouldRenderEntry: [
            (s) => [s.variant, s.effectiveTarget],
            (variant, target): boolean => variantShowsEntry(variant) && target !== null,
        ],
        shouldRenderCog: [(s) => [s.variant], (variant): boolean => variantAllowsOverride(variant)],
    }),

    listeners(({ actions, values }) => ({
        setOverride: ({ override }) => {
            const teamId = currentTeamId()
            if (teamId !== null) {
                try {
                    window.localStorage.setItem(localStorageOverrideKey(teamId), JSON.stringify(override))
                } catch {
                    // ignore — override is best-effort persistence in localStorage
                }
            }
            posthog.capture('promoted product config changed', {
                variant: values.variant,
                from: values.promotedProductIntent,
                to: override.value,
                kind: override.kind,
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
                kind: null,
            })
        },
        showConfigureModal: () => {
            // Seed the pending fields from the current effectiveTarget so the
            // modal always opens reflecting the user's current promoted product,
            // even after Reset-to-default or a fresh page load.
            const target = values.effectiveTarget
            actions.setPendingKind(target?.kind ?? 'product')
            actions.setPendingProduct(target?.kind === 'product' ? target.value : 'product_analytics')
            actions.setPendingUrl(target?.kind === 'url' ? target.value : '')
            posthog.capture('promoted product config opened', {
                variant: values.variant,
                current_target_kind: target?.kind ?? null,
                current_target_value: target?.value ?? null,
            })
        },
        trackPromotedProductClick: () => {
            const target = values.effectiveTarget
            if (!target) {
                return
            }
            posthog.capture('promoted product clicked', {
                variant: values.variant,
                kind: target.kind,
                product_key: target.kind === 'product' ? target.value : null,
                value: target.value,
            })
        },
    })),

    afterMount(({ actions }) => {
        actions.refreshIntentFromStorage()
        actions.refreshOverrideFromStorage()
    }),
])

export function promotedProductTargetToUrl(target: PromotedProductTarget): string | null {
    if (target.kind === 'product') {
        return PRODUCT_KEY_TO_URL[target.value] ?? null
    }
    return target.value
}
