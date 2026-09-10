import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { renderHook } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'

import { RestrictionScope, useRestrictedArea, useRestrictedAreaCheck } from './RestrictedArea'

describe('RestrictedArea', () => {
    const adminOnly = {
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    }

    beforeEach(() => {
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            membership_level: OrganizationMembershipLevel.Member,
        })
        organizationLogic.mount()
    })

    it('separates a pending organization from a denial', () => {
        organizationLogic.actions.loadCurrentOrganizationSuccess(null)

        const { result } = renderHook(() => useRestrictedAreaCheck(adminOnly))

        expect(result.current.isLoading).toBe(true)
        expect(result.current.restrictionReason).toBeNull()
    })

    it('reads the membership again when the user lands on a restricted area', async () => {
        await expectLogic(organizationLogic, () => {
            renderHook(() => useRestrictedAreaCheck(adminOnly))
        }).toDispatchActions(['loadCurrentOrganization'])

        expect(renderHook(() => useRestrictedAreaCheck(adminOnly)).result.current.restrictionReason).toEqual(
            'This area is restricted to organization admins and up. Your level is member.'
        )
    })

    it('leaves the membership alone when the user has access', async () => {
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            membership_level: OrganizationMembershipLevel.Admin,
        })

        await expectLogic(organizationLogic, () => {
            renderHook(() => useRestrictedAreaCheck(adminOnly))
        }).toNotHaveDispatchedActions(['loadCurrentOrganization'])
    })

    it('keeps reporting the pending organization as a reason for `useRestrictedArea` callers', () => {
        organizationLogic.actions.loadCurrentOrganizationSuccess(null)

        const { result } = renderHook(() => useRestrictedArea(adminOnly))

        expect(result.current).toEqual('Loading current organization…')
    })
})
