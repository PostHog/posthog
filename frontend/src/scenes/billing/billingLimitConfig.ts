import { BillingProductV2AddonType, BillingProductV2Type, BillingType } from '~/types'

const MAX_BILLING_LIMIT: number = 50000

export const POSTHOG_CODE_USAGE_PRODUCT_KEY = 'posthog_code_usage'
export const POSTHOG_CODE_BILLING_LIMIT_MAX: number = 3000

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

const BILLING_LIMIT_CONFIG_BY_PRODUCT: Record<string, BillingLimitConfigResolver> = {
    [POSTHOG_CODE_USAGE_PRODUCT_KEY]: ({ billing, customLimitUsd, billingLimitNextPeriod }) => {
        if (!billing?.startup_program_label) {
            return null
        }

        return {
            max: POSTHOG_CODE_BILLING_LIMIT_MAX,
            help: 'Code billing limits can be set from $0 to $3,000 per month.',
            removalDisabledReason: "Code billing limits can't be removed. Set the limit to $0 instead.",
            maxExceededError: "Code billing limits can't exceed $3,000 per month.",
            currentAboveMaxNotice:
                customLimitUsd !== null &&
                customLimitUsd > POSTHOG_CODE_BILLING_LIMIT_MAX &&
                billingLimitNextPeriod !== null &&
                billingLimitNextPeriod <= POSTHOG_CODE_BILLING_LIMIT_MAX
                    ? `Current usage is already above the Code billing limit cap, so this period's limit stays at $${customLimitUsd.toLocaleString()}. The $${billingLimitNextPeriod.toLocaleString()} limit starts next period.`
                    : null,
        }
    },
}

export const getBillingLimitConfig = (context: BillingLimitConfigContext): BillingLimitConfig => {
    const productConfig = BILLING_LIMIT_CONFIG_BY_PRODUCT[context.product.type]?.(context)

    return {
        ...DEFAULT_BILLING_LIMIT_CONFIG,
        ...productConfig,
    }
}
