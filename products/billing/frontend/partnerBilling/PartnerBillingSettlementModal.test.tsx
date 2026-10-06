import { act, cleanup, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PartnerPayerSettlementDetailApi } from '../generated/api.schemas'
import { PartnerBillingSettlementModal } from './PartnerBillingSettlementModal'
import { partnerBillingSettlementsLogic } from './partnerBillingSettlementsLogic'

const APPLICATION_ID = '0192d7c4-5b6e-7000-8000-00000000a001'
const SETTLEMENT: PartnerPayerSettlementDetailApi = {
    settlement_id: 'stl_credit_example',
    amount_cents: 10000,
    currency: 'USD',
    status: 'paid',
    invoices: [],
}

describe('PartnerBillingSettlementModal', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        { credit_amount_cents: 2500, amount_cents: 7500, credit: '$25.00', charge: '$75.00' },
        { credit_amount_cents: 10000, amount_cents: 0, credit: '$100.00', charge: '$0.00' },
    ])('explains a settlement with $credit_amount_cents cents of credit', async (amounts) => {
        const settlement = {
            ...SETTLEMENT,
            gross_amount_cents: 10000,
            credit_amount_cents: amounts.credit_amount_cents,
            amount_cents: amounts.amount_cents,
        }
        useMocks({
            get: {
                '/api/organizations/:organization_id/partner_billing/:id/': { billing_enabled: true },
                '/api/organizations/:organization_id/partner_billing/:id/organizations/': { count: 0, results: [] },
                '/api/organizations/:organization_id/partner_billing/:id/settlements/': {
                    count: 1,
                    results: [settlement],
                },
                '/api/organizations/:organization_id/partner_billing/:id/settlements/:settlement_id/': settlement,
            },
        })
        initKeaTests()
        const logic = partnerBillingSettlementsLogic({ applicationId: APPLICATION_ID })
        logic.mount()
        act(() => logic.actions.openSettlement(settlement.settlement_id))

        render(<PartnerBillingSettlementModal applicationId={APPLICATION_ID} />)

        expect((await screen.findByText('Invoice total')).parentElement?.textContent).toContain('$100.00')
        expect(screen.getByText('Credits applied').parentElement?.textContent).toContain(amounts.credit)
        expect(screen.getByText('Net charge').parentElement?.textContent).toContain(amounts.charge)
        expect(screen.getByText('Amount settled')).not.toBeNull()
        expect(screen.queryByText('Amount')).toBeNull()

        for (const withoutCredit of [
            SETTLEMENT,
            { ...SETTLEMENT, gross_amount_cents: 10000, credit_amount_cents: 0 },
        ]) {
            act(() => logic.actions.loadPartnerBillingSettlementSuccess(withoutCredit))
            expect(screen.getByText('Amount').parentElement?.textContent).toContain('$100.00')
            expect(screen.queryByText('Invoice total')).toBeNull()
            expect(screen.queryByText('Credits applied')).toBeNull()
            expect(screen.queryByText('Net charge')).toBeNull()
            expect(screen.getByText('Charged')).not.toBeNull()
        }
        logic.unmount()
    })
})
