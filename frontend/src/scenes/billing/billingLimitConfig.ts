import { BillingProductV2AddonType, BillingProductV2Type, BillingType } from '~/types'

export const MAX_BILLING_LIMIT: number = 50000

export const POSTHOG_CODE_USAGE_PRODUCT_KEY = 'posthog_code_usage'
export const REPLAY_VISION_PRODUCT_KEY = 'replay_vision'
export const STARTUP_PROGRAM_BILLING_LIMIT_MAX: number = 3000

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

// Mirrors the caps the billing service enforces for startup-program customers, so the form
// rejects out-of-range limits before the API does. The billing API product names are too
// verbose for copy (e.g. "PostHog Code (usage-based)").
const startupProgramCapResolver = (productName: string): BillingLimitConfigResolver => {
    return ({ billing, customLimitUsd, billingLimitNextPeriod }) => {
        if (!billing?.startup_program_label) {
            return null
        }

        const cap = STARTUP_PROGRAM_BILLING_LIMIT_MAX
        return {
            max: cap,
            help: `While your organization is in the startup program, ${productName} billing limits can be set from $0 to $${cap.toLocaleString()} per month.`,
            removalDisabledReason: `While your organization is in the startup program, ${productName} billing limits can't be removed. Set the limit to $0 instead.`,
            maxExceededError: `While your organization is in the startup program, ${productName} billing limits can't exceed $${cap.toLocaleString()} per month.`,
            currentAboveMaxNotice:
                customLimitUsd !== null &&
                customLimitUsd > cap &&
                billingLimitNextPeriod !== null &&
                billingLimitNextPeriod <= cap
                    ? `Current usage is already above the startup program cap, so this period's limit stays at $${customLimitUsd.toLocaleString()}. The $${billingLimitNextPeriod.toLocaleString()} limit starts next period.`
                    : null,
        }
    }
}

const BILLING_LIMIT_CONFIG_BY_PRODUCT: Record<string, BillingLimitConfigResolver> = {
    [POSTHOG_CODE_USAGE_PRODUCT_KEY]: startupProgramCapResolver('Code'),
    [REPLAY_VISION_PRODUCT_KEY]: startupProgramCapResolver('Replay vision'),
}

export const getBillingLimitConfig = (context: BillingLimitConfigContext): BillingLimitConfig => {
    const productConfig = BILLING_LIMIT_CONFIG_BY_PRODUCT[context.product.type]?.(context)

    return {
        ...DEFAULT_BILLING_LIMIT_CONFIG,
        ...productConfig,
    }
}
