import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { availableOnboardingProducts } from './utils'

/** Step keys whose default `<Capitalized> <words>` rendering doesn't read well as a title. */
const STEP_KEY_TITLE_OVERRIDES: Partial<Record<OnboardingStepKey, string>> = {
    [OnboardingStepKey.LINK_DATA]: 'Import data',
}

/**
 * Render a step key as a human-readable title. Defaults to capitalising the first word
 * of the snake_cased key (`product_configuration` → `Product configuration`); known
 * keys with awkward defaults are overridden in `STEP_KEY_TITLE_OVERRIDES`.
 */
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

/** Hard cap on number of secondary products a flow can include. Way beyond any real flow. */
export const MAX_WITH_PRODUCTS = 16
// Defense-in-depth: bound the intermediate array allocated by `String.split`
// before dedupe/filter. Browsers cap URL length already, but limiting the
// worst-case allocation costs us nothing.
const MAX_RAW_PRODUCT_TOKENS = 64

/**
 * Parse a CSV-formatted `?with=` (or legacy `?secondary=`) URL parameter into a list of
 * recognised `ProductKey`s. Defends against malformed input by:
 *   - bounding the raw `String.split` array (`MAX_RAW_PRODUCT_TOKENS`),
 *   - deduping BEFORE truncation (so an attacker can't push valid keys out of the
 *     final array by stuffing the head with duplicates),
 *   - filtering against the registry (`availableOnboardingProducts`),
 *   - capping the final length (`MAX_WITH_PRODUCTS`).
 */
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

/**
 * Element-wise strict equality. kea reducers compare by reference, so re-emitting an
 * identical-but-fresh array still triggers downstream selector recomputes — this
 * helper lets the URL handler short-circuit when nothing changed.
 */
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
