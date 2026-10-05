import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PartnerPayerStatusApi } from '../generated/api.schemas'
import { partnerBillingLogic } from './partnerBillingLogic'

const APPLICATION_ID = '0192d7c4-5b6e-7000-8000-00000000a001'
const SIGNING_SECRET = 'whsec_ZXhhbXBsZS1zZWNyZXQ='

const PAYER: PartnerPayerStatusApi = {
    name: 'Example Partner Inc.',
    billing_enabled: true,
    has_payment_method: true,
    webhook: { url: 'https://hooks.example.com/posthog', secret_created_at: null },
}

describe('partnerBillingLogic', () => {
    let logic: ReturnType<typeof partnerBillingLogic.build>

    beforeEach(() => {
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
        })
        initKeaTests()
        logic = partnerBillingLogic({ applicationId: APPLICATION_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
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
})
