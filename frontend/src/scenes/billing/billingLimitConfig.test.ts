import { BillingProductV2Type, BillingType, StartupProgramLabel } from '~/types'

import { BillingLimitConfig, getBillingLimitConfig, STARTUP_PROGRAM_BILLING_LIMIT_MAX } from './billingLimitConfig'

describe('getBillingLimitConfig', () => {
    const getConfig = (productType: string, startupProgramLabel: StartupProgramLabel | null): BillingLimitConfig =>
        getBillingLimitConfig({
            billing: { startup_program_label: startupProgramLabel } as BillingType,
            product: { type: productType } as BillingProductV2Type,
            customLimitUsd: null,
            billingLimitNextPeriod: null,
        })

    it.each(['posthog_code_usage', 'replay_vision'])(
        'caps %s for startup program customers and explains why',
        (productType) => {
            const config = getConfig(productType, StartupProgramLabel.YC)
            expect(config.max).toBe(STARTUP_PROGRAM_BILLING_LIMIT_MAX)
            expect(config.removalDisabledReason).toBeTruthy()
            expect(config.help).toContain('startup program')
            expect(config.maxExceededError).toContain('startup program')
        }
    )

    it.each(['posthog_code_usage', 'replay_vision', 'product_analytics'])(
        'does not cap %s without startup program enrollment',
        (productType) => {
            const config = getConfig(productType, null)
            expect(config.max).toBe(50000)
            expect(config.removalDisabledReason).toBeNull()
            expect(config.help).toBeNull()
        }
    )
})
