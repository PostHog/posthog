import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PartnerPayerSettlementApi } from '../generated/api.schemas'
import { partnerBillingSettlementsLogic } from './partnerBillingSettlementsLogic'

const APPLICATION_ID = '0192d7c4-5b6e-7000-8000-00000000a001'

const PAID_SETTLEMENT: PartnerPayerSettlementApi = {
    settlement_id: 'stl_paid',
    period_start: '2026-08-01T00:00:00Z',
    period_end: '2026-09-01T00:00:00Z',
    amount_cents: 98000,
    currency: 'usd',
    status: 'paid',
    attempt_count: 1,
    next_attempt_at: null,
    paid_at: '2026-09-02T00:00:00Z',
}
const FAILED_SETTLEMENT: PartnerPayerSettlementApi = {
    ...PAID_SETTLEMENT,
    settlement_id: 'stl_failed',
    period_start: '2026-09-01T00:00:00Z',
    period_end: '2026-10-01T00:00:00Z',
    status: 'failed',
    attempt_count: 2,
    next_attempt_at: '2026-10-08T00:00:00Z',
    paid_at: null,
}

describe('partnerBillingSettlementsLogic', () => {
    let logic: ReturnType<typeof partnerBillingSettlementsLogic.build>
    let retriedSettlementIds: string[]

    beforeEach(() => {
        retriedSettlementIds = []
        useMocks({
            get: {
                '/api/organizations/:organization_id/partner_billing/:id/': { billing_enabled: true, past_due: true },
                '/api/organizations/:organization_id/partner_billing/:id/settlements/': {
                    count: 2,
                    results: [FAILED_SETTLEMENT, PAID_SETTLEMENT],
                },
            },
            post: {
                '/api/organizations/:organization_id/partner_billing/:id/settlements/:settlement_id/retry/': ({
                    params,
                }) => {
                    retriedSettlementIds.push(String(params.settlement_id))
                    return [
                        200,
                        { ...FAILED_SETTLEMENT, status: 'paid', attempt_count: 3, paid_at: '2026-10-05T00:00:00Z' },
                    ]
                },
            },
        })
        initKeaTests()
        logic = partnerBillingSettlementsLogic({ applicationId: APPLICATION_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('charges a failed settlement again, refuses any other, and refreshes the past-due state', async () => {
        await expectLogic(logic).toDispatchActions(['loadPartnerBillingSettlementsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.retrySettlement(PAID_SETTLEMENT)
        })
            .toFinishAllListeners()
            .toNotHaveDispatchedActions(['retryPartnerBillingSettlement'])
        expect(retriedSettlementIds).toEqual([])

        await expectLogic(logic, () => {
            logic.actions.retrySettlement(FAILED_SETTLEMENT)
        })
            .toDispatchActions(['retryPartnerBillingSettlementSuccess', 'loadPartnerBillingPayer'])
            .toMatchValues({ retryingSettlementId: null })
        expect(retriedSettlementIds).toEqual(['stl_failed'])
        expect(logic.values.settlements?.results.map(({ settlement_id, status }) => [settlement_id, status])).toEqual([
            ['stl_failed', 'paid'],
            ['stl_paid', 'paid'],
        ])
    })
})
