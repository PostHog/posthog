import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { act, renderHook } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { RestrictionScope, useRestrictedArea, useRestrictedAreaCheck } from './RestrictedArea'

describe('RestrictedArea', () => {
    const adminOnly = {
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    }

    /** Keeps the read in flight, so the test owns whether the organization ever arrives. */
    const pendingOrganizationRead = { get: { '/api/organizations/@current': () => new Promise<never>(() => {}) } }

    beforeEach(() => {
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            membership_level: OrganizationMembershipLevel.Member,
        })
        organizationLogic.mount()
    })

    it('separates a pending organization from a denial', () => {
        useMocks(pendingOrganizationRead)
        organizationLogic.actions.loadCurrentOrganizationSuccess(null)
        organizationLogic.actions.loadCurrentOrganization()

        const { result } = renderHook(() => useRestrictedAreaCheck(adminOnly))

        expect(result.current.isLoading).toBe(true)
        expect(result.current.restrictionReason).toBeNull()
    })

    it('offers a retry when the organization read finishes with nothing', async () => {
        useMocks(pendingOrganizationRead)
        organizationLogic.actions.loadCurrentOrganizationSuccess(null)

        const { result } = renderHook(() => useRestrictedAreaCheck(adminOnly))

        expect(result.current.isLoading).toBe(false)
        expect(result.current.restrictionReason).toEqual("We couldn't check your access to the current organization.")

        await expectLogic(organizationLogic, () => {
            act(() => result.current.revalidate())
        }).toDispatchActions(['loadCurrentOrganization'])
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
