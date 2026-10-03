import { BillingProductV2AddonType, BillingProductV2Type, BillingType } from '~/types'

export const MAX_BILLING_LIMIT: number = 50000

export const POSTHOG_CODE_USAGE_PRODUCT_KEY = 'posthog_code_usage'
export const REPLAY_VISION_PRODUCT_KEY = 'replay_vision'
export const STARTUP_PROGRAM_BILLING_LIMIT_MAX_BY_PRODUCT = {
    [POSTHOG_CODE_USAGE_PRODUCT_KEY]: 500,
    [REPLAY_VISION_PRODUCT_KEY]: 3000,
} as const satisfies Record<string, number>

export type BillingLimitConfig = {
    max: number
    help: string | null
    removalDisabledReason: string | null
    maxExceededError: string
    currentAboveMaxNotice: string | null
}

type BillingLimitConfigContext = {
    billing: BillingType | null
    product: BillingProductV2Type | BillingProductV2AddonType
    customLimitUsd: number | null
    billingLimitNextPeriod: number | null
}

const DEFAULT_BILLING_LIMIT_CONFIG: BillingLimitConfig = {
    max: MAX_BILLING_LIMIT,
    help: null,
    removalDisabledReason: null,
    maxExceededError: 'Please enter a number less than 50,000',
    currentAboveMaxNotice: null,
}

type BillingLimitConfigResolver = (context: BillingLimitConfigContext) => Partial<BillingLimitConfig> | null

const currentAboveStartupCapNotice = (
    productName: string,
    cap: number,
    customLimitUsd: number | null,
    billingLimitNextPeriod: number | null
): string | null => {
    if (customLimitUsd === null || customLimitUsd <= cap) {
        return null
    }

    if (billingLimitNextPeriod !== null && billingLimitNextPeriod <= cap) {
        return `This period's ${productName} billing limit is above the startup program cap, so it stays at $${customLimitUsd.toLocaleString()}. The $${billingLimitNextPeriod.toLocaleString()} limit starts next period.`
    }

    return `This period's ${productName} billing limit is above the startup program cap, so future edits must be $${cap.toLocaleString()} or less.`
}

// Mirrors the caps the billing service enforces for startup-program customers, so the form
// rejects out-of-range limits before the API does. The billing API product names are too
// verbose for copy (e.g. "PostHog Desktop (usage-based)").
const startupProgramCapResolver = (productName: string, cap: number): BillingLimitConfigResolver => {
    return ({ billing, customLimitUsd, billingLimitNextPeriod }) => {
        if (!billing?.startup_program_label) {
            return null
        }

        return {
            max: cap,
            help: `While your organization is in the startup program, ${productName} billing limits can be set from $0 to $${cap.toLocaleString()} per month.`,
            removalDisabledReason: `While your organization is in the startup program, ${productName} billing limits can't be removed. Set the limit to $0 instead.`,
            maxExceededError: `While your organization is in the startup program, ${productName} billing limits can't exceed $${cap.toLocaleString()} per month.`,
            currentAboveMaxNotice: currentAboveStartupCapNotice(
                productName,
                cap,
                customLimitUsd,
                billingLimitNextPeriod
            ),
        }
    }
}

const BILLING_LIMIT_CONFIG_BY_PRODUCT: Record<string, BillingLimitConfigResolver> = {
    [POSTHOG_CODE_USAGE_PRODUCT_KEY]: startupProgramCapResolver(
        'Desktop',
        STARTUP_PROGRAM_BILLING_LIMIT_MAX_BY_PRODUCT[POSTHOG_CODE_USAGE_PRODUCT_KEY]
    ),
    [REPLAY_VISION_PRODUCT_KEY]: startupProgramCapResolver(
        'Replay vision',
        STARTUP_PROGRAM_BILLING_LIMIT_MAX_BY_PRODUCT[REPLAY_VISION_PRODUCT_KEY]
    ),
}

export const getBillingLimitConfig = (context: BillingLimitConfigContext): BillingLimitConfig => {
    const productConfig = BILLING_LIMIT_CONFIG_BY_PRODUCT[context.product.type]?.(context)

    return {
        ...DEFAULT_BILLING_LIMIT_CONFIG,
        ...productConfig,
    }
}
