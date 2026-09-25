import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { OrganizationMembershipLevel } from 'lib/constants'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, PreflightStatus, UserType } from '~/types'

import meCurrent from './__mocks__/@me.json'
import { payGateMiniLogic } from './payGateMiniLogic'

describe('payGateMiniLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/_preflight': [200, { ...preflightJson, cloud: true }],
                '/api/billing': [200, billingJson],
                '/api/users/@me': [200, meCurrent],
            },
        })
        initKeaTests()
    })

    const mountAs = (membershipLevel: OrganizationMembershipLevel): ReturnType<typeof payGateMiniLogic> => {
        preflightLogic.mount()
        userLogic.mount()
        organizationLogic.mount()
        billingLogic.mount()
        const logic = payGateMiniLogic({ feature: AvailableFeature.SUBSCRIPTIONS })
        logic.mount()

        preflightLogic.actions.loadPreflightSuccess({ ...preflightJson, cloud: true } as unknown as PreflightStatus)
        userLogic.actions.loadUserSuccess(meCurrent as unknown as UserType)
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            membership_level: membershipLevel,
        })
        billingLogic.actions.loadBillingSuccess(billingJson)

        return logic
    }

    it('does not send a member to the billing page they cannot open', () => {
        const logic = mountAs(OrganizationMembershipLevel.Member)

        expect(logic.values.gateVariant).toBe('add-card')
        expect(logic.values.mustAskAdminToUpgrade).toBe(true)
        expect(logic.values.ctaLink).toBeUndefined()
        expect(logic.values.isPaymentEntryFlow).toBe(false)
    })

    it('keeps the billing link for an admin', () => {
        const logic = mountAs(OrganizationMembershipLevel.Admin)

        expect(logic.values.gateVariant).toBe('add-card')
        expect(logic.values.mustAskAdminToUpgrade).toBe(false)
        expect(logic.values.ctaLink).toContain('/organization/billing')
    })
})
