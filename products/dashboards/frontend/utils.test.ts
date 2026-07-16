import { DashboardPrivilegeLevel } from 'lib/constants'

import { AccessControlLevel } from '~/types'

import { canEditDashboard } from './utils'

describe('dashboards utils', () => {
    describe('canEditDashboard', () => {
        it.each([
            // RBAC editor on an unrestricted dashboard can edit.
            [AccessControlLevel.Editor, DashboardPrivilegeLevel.CanEdit, true],
            // RBAC editor blocked by the legacy restriction (the reported bug) cannot edit.
            [AccessControlLevel.Editor, DashboardPrivilegeLevel.CanView, false],
            // RBAC viewer cannot edit even when legacy would allow it.
            [AccessControlLevel.Viewer, DashboardPrivilegeLevel.CanEdit, false],
            // Both systems denying edits keeps it non-editable.
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
