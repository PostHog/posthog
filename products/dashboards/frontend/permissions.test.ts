import { DashboardPrivilegeLevel } from 'lib/constants'

import { AccessControlLevel } from '~/types'

import { canEditDashboard } from './permissions'

describe('dashboard permissions', () => {
    describe('canEditDashboard', () => {
        it.each([
            [AccessControlLevel.Editor, DashboardPrivilegeLevel.CanEdit, true],
            [AccessControlLevel.Editor, DashboardPrivilegeLevel.CanView, false],
            [AccessControlLevel.Viewer, DashboardPrivilegeLevel.CanEdit, false],
            [AccessControlLevel.Viewer, DashboardPrivilegeLevel.CanView, false],
        ])('with RBAC %s and legacy privilege %s returns %s', (userAccessLevel, effectivePrivilegeLevel, expected) => {
            expect(
                canEditDashboard({
                    user_access_level: userAccessLevel,
                    effective_privilege_level: effectivePrivilegeLevel,
                })
            ).toBe(expected)
        })

        it('lets RBAC decide when the legacy privilege is absent', () => {
            expect(canEditDashboard({ user_access_level: AccessControlLevel.Editor })).toBe(true)
            expect(canEditDashboard({ user_access_level: AccessControlLevel.Viewer })).toBe(false)
        })
    })
})
