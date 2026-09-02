import { BillingProductV2Type, BillingType, StartupProgramLabel } from '~/types'

import {
    BillingLimitConfig,
    getBillingLimitConfig,
    MAX_BILLING_LIMIT,
    POSTHOG_CODE_USAGE_PRODUCT_KEY,
    REPLAY_VISION_PRODUCT_KEY,
} from './billingLimitConfig'

describe('getBillingLimitConfig', () => {
    const getConfig = (
        productType: string,
        startupProgramLabel: StartupProgramLabel | null,
        limits: { customLimitUsd?: number | null; billingLimitNextPeriod?: number | null } = {}
    ): BillingLimitConfig =>
        getBillingLimitConfig({
            billing: { startup_program_label: startupProgramLabel } as BillingType,
            product: { type: productType } as BillingProductV2Type,
            customLimitUsd: limits.customLimitUsd ?? null,
            billingLimitNextPeriod: limits.billingLimitNextPeriod ?? null,
        })

    it.each([
        [POSTHOG_CODE_USAGE_PRODUCT_KEY, 'Desktop', 500],
        [REPLAY_VISION_PRODUCT_KEY, 'Replay vision', 3000],
    ])('caps %s for startup program customers and explains why', (productType, productName, cap) => {
        const config = getConfig(productType, StartupProgramLabel.YC)
        expect(config.max).toBe(cap)
        expect(config.removalDisabledReason).toBeTruthy()
        expect(config.help).toContain(`${productName} billing limits`)
        expect(config.help).toContain(`$${cap.toLocaleString()}`)
        expect(config.maxExceededError).toContain(`${productName} billing limits`)
        expect(config.maxExceededError).toContain(`$${cap.toLocaleString()}`)
    })

    it.each(['posthog_code_usage', 'replay_vision', 'product_analytics'])(
        'does not cap %s without startup program enrollment',
        (productType) => {
            const config = getConfig(productType, null)
            expect(config.max).toBe(MAX_BILLING_LIMIT)
            expect(config.removalDisabledReason).toBeNull()
            expect(config.help).toBeNull()
        }
    )

    it.each([
        [POSTHOG_CODE_USAGE_PRODUCT_KEY, 750, 500, 'The $500 limit starts next period.'],
        [POSTHOG_CODE_USAGE_PRODUCT_KEY, 750, null, 'future edits must be $500 or less.'],
        [POSTHOG_CODE_USAGE_PRODUCT_KEY, 750, 600, 'future edits must be $500 or less.'],
        [REPLAY_VISION_PRODUCT_KEY, 3750, 2000, 'The $2,000 limit starts next period.'],
        [REPLAY_VISION_PRODUCT_KEY, 3750, 5000, 'future edits must be $3,000 or less.'],
        [REPLAY_VISION_PRODUCT_KEY, null, 2000, null],
    ])(
        'for %s with current limit %p and next period limit %p, above-cap notice includes %p',
        (productType, customLimitUsd, billingLimitNextPeriod, expectedNotice) => {
            const config = getConfig(productType, StartupProgramLabel.YC, {
                customLimitUsd,
                billingLimitNextPeriod,
            })
            if (expectedNotice) {
                expect(config.currentAboveMaxNotice).toContain(expectedNotice)
            } else {
                expect(config.currentAboveMaxNotice).toBeNull()
            }
        }
    )
})
