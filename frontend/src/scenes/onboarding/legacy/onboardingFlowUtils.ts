import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

const STEP_KEY_TITLE_OVERRIDES: Partial<Record<OnboardingStepKey, string>> = {
    [OnboardingStepKey.LINK_DATA]: 'Import data',
}

/**
 * Step keys that can join the flow asynchronously after it first builds: `plans`
 * appears once billing loads, `invite_teammates` once org invite permissions
 * resolve, and `link_data` is appended for product-analytics primaries. A URL
 * requesting one of these must not be self-corrected away just because the step
 * isn't in the flow yet.
 */
const ASYNC_APPENDED_STEP_KEYS: string[] = [
    OnboardingStepKey.PLANS,
    OnboardingStepKey.INVITE_TEAMMATES,
    OnboardingStepKey.LINK_DATA,
]

/**
 * Whether a requested step id might still be emitted into the flow once async data
 * (billing, org membership) loads. Product-provided steps (install, configure, …)
 * are contributed synchronously the moment the flow builds, so a bare product-level
 * step key missing from a built flow will never appear — e.g. `?step=install` for a
 * product whose provider emits no install step — and must be self-corrected instead
 * of leaving the host on a spinner forever.
 *
 * A `?` or `&` means query params fused into the step value (a mangled URL) — never
 * treat that as pending. Namespaced ids (`install:logs`) are conservatively treated
 * as pending: they include the namespaced forms of the async-appended steps
 * (`plans:<product>`), which must keep waiting for billing.
 */
export const mayStepAppearLater = (stepId: string): boolean =>
    !/[?&]/.test(stepId) && (ASYNC_APPENDED_STEP_KEYS.includes(stepId) || stepId.includes(':'))

export const stepKeyToTitle = (stepKey?: OnboardingStepKey): undefined | string => {
    if (!stepKey) {
        return undefined
    }
    if (STEP_KEY_TITLE_OVERRIDES[stepKey]) {
        return STEP_KEY_TITLE_OVERRIDES[stepKey]
    }
    return stepKey
        .split('_')
        .map((part, i) => (i == 0 ? part[0].toUpperCase() + part.substring(1) : part))
        .join(' ')
}

export const MAX_WITH_PRODUCTS = 16
const MAX_RAW_PRODUCT_TOKENS = 64

// Dedupe before truncating so duplicate-stuffing can't push valid keys out of the result.
export const parseProductsParam = (raw: unknown): ProductKey[] => {
    const value = typeof raw === 'string' ? raw : ''
    if (!value) {
        return []
    }
    const unique = Array.from(new Set(value.split(',').slice(0, MAX_RAW_PRODUCT_TOKENS)))
    return unique
        .filter((k: string) => Object.hasOwn(availableOnboardingProducts, k))
        .slice(0, MAX_WITH_PRODUCTS) as ProductKey[]
}

export const arraysEqual = <T>(a: readonly T[], b: readonly T[]): boolean => {
    if (a.length !== b.length) {
        return false
    }
    for (let i = 0; i < a.length; i++) {
        if (a[i] !== b[i]) {
            return false
        }
    }
    return true
}
