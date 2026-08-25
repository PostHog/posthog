import { BillingProductV2Type, BillingType, StartupProgramLabel } from '~/types'

import {
    BillingLimitConfig,
    getBillingLimitConfig,
    MAX_BILLING_LIMIT,
    POSTHOG_CODE_USAGE_PRODUCT_KEY,
    REPLAY_VISION_PRODUCT_KEY,
    STARTUP_PROGRAM_BILLING_LIMIT_MAX_BY_PRODUCT,
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
        [POSTHOG_CODE_USAGE_PRODUCT_KEY, 750, 500, true],
        [POSTHOG_CODE_USAGE_PRODUCT_KEY, 750, 600, false],
        [REPLAY_VISION_PRODUCT_KEY, 3750, 2000, true],
        [REPLAY_VISION_PRODUCT_KEY, 3750, 5000, false],
        [REPLAY_VISION_PRODUCT_KEY, null, 2000, false],
    ])(
        'for %s with current limit %p and next period limit %p, above-cap notice shown: %p',
        (productType, customLimitUsd, billingLimitNextPeriod, noticeShown) => {
            const config = getConfig(productType, StartupProgramLabel.YC, {
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

    it('exports startup program caps by product', () => {
        expect(STARTUP_PROGRAM_BILLING_LIMIT_MAX_BY_PRODUCT).toEqual({
            [POSTHOG_CODE_USAGE_PRODUCT_KEY]: 500,
            [REPLAY_VISION_PRODUCT_KEY]: 3000,
        })
    })
})
