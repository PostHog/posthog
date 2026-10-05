import type { PartnerPayerStatusApi } from '../generated/api.schemas'
import { PartnerBillingSpendingFormValues, spendingChanges, spendingFormValues } from './partnerBillingForms'

const PAYER: PartnerPayerStatusApi = {
    spend: { month_to_date_usd: '1200.50', alert_usd: '1000.00', cap_usd: '5000.00', capped: false },
    default_limits_usd: { product_analytics: 500, session_replay: 100 },
}

describe('spendingChanges', () => {
    it.each<[string, Partial<PartnerBillingSpendingFormValues>, ReturnType<typeof spendingChanges>]>([
        ['an untouched form', {}, {}],
        [
            'a cleared alert and a new cap',
            { spend_alert_usd: '', spend_cap_usd: '7500' },
            { spend_alert_usd: null, spend_cap_usd: '7500' },
        ],
        [
            'a cleared limit, a new limit and an untouched limit',
            { default_limits_usd: { product_analytics: null, session_replay: 100, surveys: 50 } },
            { default_limits_usd: { product_analytics: null, surveys: 50 } },
        ],
    ])('for %s, sends only the changes, with null for anything cleared', (_name, edits, expected) => {
        expect(spendingChanges(PAYER, { ...spendingFormValues(PAYER), ...edits })).toEqual(expected)
    })
})
