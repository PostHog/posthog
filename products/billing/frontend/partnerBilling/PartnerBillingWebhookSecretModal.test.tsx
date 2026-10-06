import { cleanup, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { partnerBillingLogic } from './partnerBillingLogic'
import { PartnerBillingWebhookSecretModal } from './PartnerBillingWebhookSecretModal'

const APPLICATION_ID = '0192d7c4-5b6e-7000-8000-00000000a001'
const SIGNING_SECRET = 'whsec_ZXhhbXBsZS1zZWNyZXQ='

describe('PartnerBillingWebhookSecretModal', () => {
    afterEach(() => {
        cleanup()
    })

    it('keeps the signing secret out of autocapture and session replay', () => {
        useMocks({
            get: { '/api/organizations/:organization_id/partner_billing/:id/': { billing_enabled: true } },
        })
        initKeaTests()
        const logic = partnerBillingLogic({ applicationId: APPLICATION_ID })
        logic.mount()
        logic.actions.rotatePartnerBillingWebhookSecretSuccess({
            secret: SIGNING_SECRET,
            created_at: '2026-10-05T12:00:00Z',
        })

        render(<PartnerBillingWebhookSecretModal applicationId={APPLICATION_ID} />)

        expect(screen.getByText(SIGNING_SECRET).closest('.ph-no-capture')).not.toBeNull()
        logic.unmount()
    })
})
