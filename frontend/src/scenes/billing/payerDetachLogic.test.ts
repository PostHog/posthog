/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { billingLogic } from 'scenes/billing/billingLogic'
import { payerDetachLogic } from 'scenes/billing/payerDetachLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType } from '~/types'

const PARTNER_PAID_BILLING: Partial<BillingType> = {
    customer_id: '',
    billing_managed_by_partner: { partner_name: 'Example Partner' },
}
const PAYER_DETACH_UNCONFIRMED_DETAIL =
    "We couldn't confirm the change with billing. Try again; it's safe to repeat. If it keeps happening, contact support."

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
        let detachBody: unknown
        useMocks({
            post: {
                '/api/billing/payer/detach': async ({ request }) => {
                    detachBody = await request.json()
                    await detachReleased
                    billingState = { customer_id: '' }
                    return [200, { detached_at: '2026-10-05T12:00:00Z' }]
                },
            },
        })
        await mountAs(OrganizationMembershipLevel.Owner)

        let releaseBilling = (): void => {}
        const billingReleased = new Promise<void>((resolve) => {
            releaseBilling = resolve
        })
        useMocks({
            get: {
                '/api/billing': async () => {
                    await billingReleased
                    return [200, billingState]
                },
            },
        })

        logic.actions.openPayerDetachModal()
        logic.actions.detachFromPayer()
        expect(logic.values.isDetachingFromPayer).toBe(true)

        releaseDetach()
        try {
            await expectLogic(logic).toDispatchActions(['detachFromPayerSuccess'])

            expect(billingLogic.values.isBillingManagedByPartner).toBe(true)
            expect(logic.values.canDetachFromPayer).toBe(false)
        } finally {
            releaseBilling()
        }
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({ isPayerDetachModalOpen: false, isDetachingFromPayer: false })
        expect(billingLogic.values.isBillingManagedByPartner).toBe(false)
        expect(detachBody).toEqual({ organization_id: MOCK_DEFAULT_ORGANIZATION.id })

        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            id: '01984035-0000-7000-8000-000000000002',
            membership_level: OrganizationMembershipLevel.Owner,
        })
        billingLogic.actions.loadBillingSuccess(PARTNER_PAID_BILLING as BillingType)
        expect(logic.values.canDetachFromPayer).toBe(true)
    })

    it('keeps the modal open with the explanation from billing when the detach fails', async () => {
        useMocks({
            post: {
                '/api/billing/payer/detach': () => [
                    502,
                    {
                        type: 'server_error',
                        code: 'payer_detach_unconfirmed',
                        detail: PAYER_DETACH_UNCONFIRMED_DETAIL,
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
            payerDetachError: PAYER_DETACH_UNCONFIRMED_DETAIL,
        })
        expect(billingLogic.values.isBillingManagedByPartner).toBe(true)
    })
})
