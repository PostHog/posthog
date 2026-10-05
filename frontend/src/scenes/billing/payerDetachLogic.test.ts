/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { billingLogic } from 'scenes/billing/billingLogic'
import { payerDetachLogic } from 'scenes/billing/payerDetachLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType } from '~/types'

const PARTNER_PAID_BILLING: Partial<BillingType> = {
    customer_id: '',
    billing_managed_by_partner: { partner_name: 'Example Partner' },
}
const PAYER_DETACH_FAILED_DETAIL =
    "Billing couldn't make the change, so your partner still pays for this organization. Try again in a few minutes, and contact support if it keeps happening."

describe('payerDetachLogic', () => {
    let billingState: Partial<BillingType>
    let logic: ReturnType<typeof payerDetachLogic.build>

    const mountAs = async (membershipLevel: OrganizationMembershipLevel): Promise<void> => {
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, {
            ...MOCK_DEFAULT_ORGANIZATION,
            membership_level: membershipLevel,
        })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling())
            .toFinishAllListeners()
            .clearHistory()
        logic = payerDetachLogic()
        logic.mount()
    }

    beforeEach(() => {
        billingState = PARTNER_PAID_BILLING
        useMocks({ get: { '/api/billing': () => [200, billingState] } })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        { level: OrganizationMembershipLevel.Owner, canDetach: true },
        { level: OrganizationMembershipLevel.Admin, canDetach: false },
    ])('offers the detach only to an owner (membership level $level)', async ({ level, canDetach }) => {
        await mountAs(level)

        expect(logic.values.canDetachFromPayer).toBe(canDetach)
    })

    it('holds the confirm while billing answers, then closes the modal and reloads billing without the partner', async () => {
        let releaseDetach = (): void => {}
        const detachReleased = new Promise<void>((resolve) => {
            releaseDetach = resolve
        })
        useMocks({
            post: {
                '/api/billing/payer/detach': async () => {
                    await detachReleased
                    billingState = { customer_id: '' }
                    return [200, { detached_at: '2026-10-05T12:00:00Z' }]
                },
            },
        })
        await mountAs(OrganizationMembershipLevel.Owner)

        logic.actions.openPayerDetachModal()
        logic.actions.detachFromPayer()
        expect(logic.values.isDetachingFromPayer).toBe(true)

        releaseDetach()
        await expectLogic(logic).toDispatchActions(['detachFromPayerSuccess']).toFinishAllListeners()

        expect(logic.values).toMatchObject({ isPayerDetachModalOpen: false, isDetachingFromPayer: false })
        expect(billingLogic.values.isBillingManagedByPartner).toBe(false)
    })

    it('keeps the modal open with the explanation from billing when the detach fails', async () => {
        useMocks({
            post: {
                '/api/billing/payer/detach': () => [
                    502,
                    {
                        type: 'server_error',
                        code: 'payer_detach_failed',
                        detail: PAYER_DETACH_FAILED_DETAIL,
                        attr: null,
                    },
                ],
            },
        })
        await mountAs(OrganizationMembershipLevel.Owner)

        logic.actions.openPayerDetachModal()
        await expectLogic(logic, () => logic.actions.detachFromPayer())
            .toDispatchActions(['detachFromPayerFailure'])
            .toFinishAllListeners()

        expect(logic.values).toMatchObject({
            isPayerDetachModalOpen: true,
            isDetachingFromPayer: false,
            payerDetachError: PAYER_DETACH_FAILED_DETAIL,
        })
        expect(billingLogic.values.isBillingManagedByPartner).toBe(true)
    })
})
