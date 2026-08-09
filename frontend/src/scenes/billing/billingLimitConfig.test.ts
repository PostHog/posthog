import { BillingProductV2Type, BillingType, StartupProgramLabel } from '~/types'

import {
    BillingLimitConfig,
    getBillingLimitConfig,
    MAX_BILLING_LIMIT,
    POSTHOG_CODE_USAGE_PRODUCT_KEY,
    REPLAY_VISION_PRODUCT_KEY,
    STARTUP_PROGRAM_BILLING_LIMIT_MAX,
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
        [POSTHOG_CODE_USAGE_PRODUCT_KEY, 'Desktop'],
        [REPLAY_VISION_PRODUCT_KEY, 'Replay vision'],
    ])('caps %s for startup program customers and explains why', (productType, productName) => {
        const config = getConfig(productType, StartupProgramLabel.YC)
        expect(config.max).toBe(STARTUP_PROGRAM_BILLING_LIMIT_MAX)
        expect(config.removalDisabledReason).toBeTruthy()
        expect(config.help).toContain(`${productName} billing limits`)
        expect(config.maxExceededError).toContain(`${productName} billing limits`)
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
        [3750, 2000, true],
        [3750, 5000, false],
        [null, 2000, false],
    ])(
        'with current limit %p and next period limit %p, above-cap notice shown: %p',
        (customLimitUsd, billingLimitNextPeriod, noticeShown) => {
            const config = getConfig('replay_vision', StartupProgramLabel.YC, {
                customLimitUsd,
                billingLimitNextPeriod,
            })
            if (noticeShown) {
                expect(config.currentAboveMaxNotice).toContain('next period')
            } else {
                expect(config.currentAboveMaxNotice).toBeNull()
            }
        }
    )
})
