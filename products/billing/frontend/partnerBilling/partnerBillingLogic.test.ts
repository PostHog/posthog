import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PartnerPayerStatusApi, PatchedPartnerPayerAdminUpdateApi } from '../generated/api.schemas'
import type { PartnerBillingSpendingFormValues } from './partnerBillingForms'
import { partnerBillingLogic } from './partnerBillingLogic'

const APPLICATION_ID = '0192d7c4-5b6e-7000-8000-00000000a001'
const SIGNING_SECRET = 'whsec_ZXhhbXBsZS1zZWNyZXQ='

const PAYER: PartnerPayerStatusApi = {
    name: 'Example Partner Inc.',
    billing_enabled: true,
    has_payment_method: true,
    webhook: { url: 'https://hooks.example.com/posthog', secret_created_at: null },
    spend: { month_to_date_usd: '1200.50', alert_usd: '1000.00', cap_usd: null, capped: false },
    default_limits_usd: { product_analytics: 500 },
}

describe('partnerBillingLogic', () => {
    let logic: ReturnType<typeof partnerBillingLogic.build>
    let payerUpdates: PatchedPartnerPayerAdminUpdateApi[]

    beforeEach(() => {
        payerUpdates = []
        useMocks({
            get: {
                '/api/organizations/:organization_id/partner_billing/:id/': PAYER,
            },
            post: {
                '/api/organizations/:organization_id/partner_billing/:id/webhook_secret/': {
                    secret: SIGNING_SECRET,
                    created_at: '2026-10-05T12:00:00Z',
                },
            },
            patch: {
                '/api/organizations/:organization_id/partner_billing/:id/': async ({ request }) => {
                    payerUpdates.push((await request.json()) as PatchedPartnerPayerAdminUpdateApi)
                    return [200, PAYER]
                },
            },
        })
        initKeaTests()
        logic = partnerBillingLogic({ applicationId: APPLICATION_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('shows a new signing secret until it is dismissed, and keeps only its creation time after that', async () => {
        await expectLogic(logic).toDispatchActions(['loadPartnerBillingPayerSuccess'])

        await expectLogic(logic, () => {
            logic.actions.rotatePartnerBillingWebhookSecret()
        })
            .toDispatchActions(['rotatePartnerBillingWebhookSecretSuccess'])
            .toMatchValues({
                webhookSecret: { secret: SIGNING_SECRET, created_at: '2026-10-05T12:00:00Z' },
                payer: { ...PAYER, webhook: { ...PAYER.webhook, secret_created_at: '2026-10-05T12:00:00Z' } },
            })

        logic.actions.dismissWebhookSecret()

        expect(logic.values.webhookSecret).toBeNull()
        expect(JSON.stringify(logic.values.payer)).not.toContain(SIGNING_SECRET)
    })

    it.each<[string, Partial<PartnerBillingSpendingFormValues>, boolean, PatchedPartnerPayerAdminUpdateApi]>([
        ['a spend alert change', { spend_alert_usd: '2000' }, false, { spend_alert_usd: '2000' }],
        [
            'a default limit change',
            { default_limits_usd: { product_analytics: 600 } },
            true,
            { default_limits_usd: { product_analytics: 600 } },
        ],
    ])('saves %s, asking first only when it changes default limits', async (_name, edits, asks, expectedUpdate) => {
        const openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        await expectLogic(logic).toDispatchActions(['loadPartnerBillingPayerSuccess'])

        logic.actions.setSpendingFormValues(edits)
        logic.actions.saveSpendingSettings()
        await expectLogic(logic).toFinishAllListeners()

        expect(openDialog).toHaveBeenCalledTimes(asks ? 1 : 0)
        if (asks) {
            expect(payerUpdates).toEqual([])
            openDialog.mock.calls[0][0].primaryButton?.onClick?.({} as React.MouseEvent<HTMLElement>)
        }
        await expectLogic(logic).toDispatchActions(['submitSpendingFormSuccess'])
        expect(payerUpdates).toEqual([expectedUpdate])
    })
})
