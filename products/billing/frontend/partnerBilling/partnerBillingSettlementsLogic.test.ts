import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PartnerPayerInvoiceApi, PartnerPayerSettlementApi } from '../generated/api.schemas'
import { partnerBillingInvoicesLogic } from './partnerBillingInvoicesLogic'
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
const CHARGED_SETTLEMENT: PartnerPayerSettlementApi = {
    ...FAILED_SETTLEMENT,
    status: 'paid',
    attempt_count: 3,
    paid_at: '2026-10-05T00:00:00Z',
}
const FAILED_SETTLEMENT_INVOICE: PartnerPayerInvoiceApi = {
    invoice_id: 'in_failed',
    settlement_id: FAILED_SETTLEMENT.settlement_id,
    status: 'open',
}

describe('partnerBillingSettlementsLogic', () => {
    let logic: ReturnType<typeof partnerBillingSettlementsLogic.build>
    let invoicesLogic: ReturnType<typeof partnerBillingInvoicesLogic.build>
    let retriedSettlementIds: string[]

    beforeEach(() => {
        retriedSettlementIds = []
        const charged = (): boolean => retriedSettlementIds.length > 0
        const invoices = (): PartnerPayerInvoiceApi[] => [
            { ...FAILED_SETTLEMENT_INVOICE, status: charged() ? 'paid' : 'open' },
        ]
        useMocks({
            get: {
                '/api/organizations/:organization_id/partner_billing/:id/': { billing_enabled: true, past_due: true },
                '/api/organizations/:organization_id/partner_billing/:id/invoices/': () => [
                    200,
                    { count: 1, results: invoices() },
                ],
                '/api/organizations/:organization_id/partner_billing/:id/settlements/': {
                    count: 2,
                    results: [FAILED_SETTLEMENT, PAID_SETTLEMENT],
                },
                '/api/organizations/:organization_id/partner_billing/:id/settlements/:settlement_id/': () => [
                    200,
                    { ...(charged() ? CHARGED_SETTLEMENT : FAILED_SETTLEMENT), invoices: invoices() },
                ],
            },
            post: {
                '/api/organizations/:organization_id/partner_billing/:id/settlements/:settlement_id/retry/': ({
                    params,
                }) => {
                    retriedSettlementIds.push(String(params.settlement_id))
                    return [200, CHARGED_SETTLEMENT]
                },
            },
        })
        initKeaTests()
        logic = partnerBillingSettlementsLogic({ applicationId: APPLICATION_ID })
        logic.mount()
        invoicesLogic = partnerBillingInvoicesLogic({ applicationId: APPLICATION_ID })
        invoicesLogic.mount()
    })

    afterEach(() => {
        invoicesLogic.unmount()
        logic.unmount()
    })

    it('charges a failed settlement again, refuses any other, and refreshes the past-due state and the invoices it paid', async () => {
        await expectLogic(logic).toDispatchActions(['loadPartnerBillingSettlementsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.retrySettlement(PAID_SETTLEMENT)
        })
            .toFinishAllListeners()
            .toNotHaveDispatchedActions(['retryPartnerBillingSettlement'])
        expect(retriedSettlementIds).toEqual([])

        logic.actions.openSettlement(FAILED_SETTLEMENT.settlement_id)
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.retrySettlement(FAILED_SETTLEMENT)
        })
            .toDispatchActions(['retryPartnerBillingSettlementSuccess', 'loadPartnerBillingPayer'])
            .toFinishAllListeners()
            .toMatchValues({ retryingSettlementId: null })
        expect(retriedSettlementIds).toEqual(['stl_failed'])
        expect(logic.values.settlements?.results.map(({ settlement_id, status }) => [settlement_id, status])).toEqual([
            ['stl_failed', 'paid'],
            ['stl_paid', 'paid'],
        ])
        expect(logic.values.openedSettlement?.invoices?.map(({ status }) => status)).toEqual(['paid'])
        expect(invoicesLogic.values.invoices?.results.map(({ status }) => status)).toEqual(['paid'])
    })
})
