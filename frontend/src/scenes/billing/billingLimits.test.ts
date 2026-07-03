/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingProductV2Type } from '~/types'

const productA = { type: 'product_analytics', name: 'Product analytics', subscribed: true } as BillingProductV2Type
const productB = { type: 'session_replay', name: 'Session replay', subscribed: true } as BillingProductV2Type

describe('billing limits', () => {
    let logicA: ReturnType<typeof billingProductLogic.build>
    let logicB: ReturnType<typeof billingProductLogic.build>
    // Mock billing service state: PATCH merges per key and echoes the full maps, like the real one.
    let serverLimits: Record<string, number>
    let serverNextPeriodLimits: Record<string, number>

    const billingPayload = (): Record<string, any> => ({
        customer_id: 'cus_test',
        products: [productA, productB],
        custom_limits_usd: { ...serverLimits },
        next_period_custom_limits_usd: { ...serverNextPeriodLimits },
    })

    const mergeIntoServerLimits = (limits: Record<string, number | null>): void => {
        for (const [key, value] of Object.entries(limits)) {
            if (value === null) {
                delete serverLimits[key]
            } else {
                serverLimits[key] = value
            }
        }
    }

    beforeEach(async () => {
        initKeaTests()
        serverLimits = { session_replay: 200 }
        serverNextPeriodLimits = { session_replay: 100 }
        useMocks({
            get: { '/api/billing': () => [200, billingPayload()] },
            patch: {
                '/api/billing': async ({ request }) => {
                    const body: any = await request.json()
                    mergeIntoServerLimits(body.custom_limits_usd ?? {})
                    if (body.reset_limit_next_period) {
                        delete serverNextPeriodLimits[body.reset_limit_next_period]
                    }
                    return [200, billingPayload()]
                },
            },
        })
        billingLogic.mount()
        logicA = billingProductLogic({ product: productA })
        logicA.mount()
        logicB = billingProductLogic({ product: productB })
        logicB.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
    })

    afterEach(() => {
        logicB?.unmount()
        logicA?.unmount()
        billingLogic.unmount()
    })

    it("saving one product's limit does not touch another product's editing state", async () => {
        logicA.actions.setIsEditingBillingLimit(true)
        logicB.actions.setIsEditingBillingLimit(true)
        logicB.actions.setBillingLimitInput(300)

        await expectLogic(billingLogic, () =>
            billingLogic.actions.updateBillingLimit(productA.type, 100)
        ).toFinishAllListeners()

        expect(billingLogic.values.billing?.custom_limits_usd).toEqual({
            product_analytics: 100,
            session_replay: 200,
        })
        expect(logicA.values.isEditingBillingLimit).toBe(false)
        expect(logicB.values.isEditingBillingLimit).toBe(true)
        expect(logicB.values.billingLimitInput).toEqual({ input: 300 })
    })

    it('tracks in-flight updates per product, not globally', async () => {
        billingLogic.actions.updateBillingLimit(productA.type, 100)

        expect(logicA.values.isLimitUpdateInFlight).toBe(true)
        expect(logicB.values.isLimitUpdateInFlight).toBe(false)

        await expectLogic(billingLogic).toFinishAllListeners()

        expect(logicA.values.isLimitUpdateInFlight).toBe(false)
    })

    it('concurrent saves both land even when the first save responds last with stale data', async () => {
        let releaseA: () => void = () => {}
        const gateA = new Promise<void>((resolve) => (releaseA = resolve))
        useMocks({
            patch: {
                '/api/billing': async ({ request }) => {
                    const body: any = await request.json()
                    mergeIntoServerLimits(body.custom_limits_usd)
                    const response = billingPayload()
                    if (productA.type in body.custom_limits_usd) {
                        await gateA // A's response arrives after B has saved, so it lacks B's new limit
                    }
                    return [200, response]
                },
            },
        })

        billingLogic.actions.updateBillingLimit(productA.type, 100)
        billingLogic.actions.updateBillingLimit(productB.type, 150)
        await expectLogic(billingLogic).toDispatchActions(['updateBillingLimitSuccess', 'loadBillingSuccess'])

        releaseA()
        await expectLogic(billingLogic).toDispatchActions(['updateBillingLimitSuccess'])

        expect(billingLogic.values.billing?.custom_limits_usd).toEqual({
            product_analytics: 100,
            session_replay: 150,
        })

        await expectLogic(billingLogic).toFinishAllListeners()
    })

    it('removing the next-period limit clears it for that product only', async () => {
        expect(logicB.values.billingLimitNextPeriod).toBe(100)

        await expectLogic(billingLogic, () =>
            billingLogic.actions.removeBillingLimitNextPeriod(productB.type)
        ).toFinishAllListeners()

        expect(logicB.values.billingLimitNextPeriod).toBeNull()
        expect(logicB.values.isLimitUpdateInFlight).toBe(false)
        expect(billingLogic.values.billing?.custom_limits_usd).toEqual({ session_replay: 200 })
    })

    it('a failed save clears the in-flight flag and keeps the editor open for a retry', async () => {
        useMocks({ patch: { '/api/billing': () => [500, {}] } })
        logicA.actions.setIsEditingBillingLimit(true)

        await expectLogic(billingLogic, () =>
            billingLogic.actions.updateBillingLimit(productA.type, 100)
        ).toFinishAllListeners()

        expect(logicA.values.isLimitUpdateInFlight).toBe(false)
        expect(logicA.values.isEditingBillingLimit).toBe(true)
        expect(billingLogic.values.billing?.custom_limits_usd).toEqual({ session_replay: 200 })
    })
})
