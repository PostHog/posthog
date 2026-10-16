import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

const STEP_KEY_TITLE_OVERRIDES: Partial<Record<OnboardingStepKey, string>> = {
    [OnboardingStepKey.LINK_DATA]: 'Import data',
}

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
