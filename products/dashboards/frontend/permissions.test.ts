import { DashboardPrivilegeLevel } from 'lib/constants'

import { AccessControlLevel } from '~/types'

import { canEditDashboard } from './permissions'

describe('dashboard permissions', () => {
    describe('canEditDashboard', () => {
        it.each([
            ['v1', AccessControlLevel.Viewer, DashboardPrivilegeLevel.CanEdit, true],
            ['v1', AccessControlLevel.Editor, DashboardPrivilegeLevel.CanView, false],
            ['v2', AccessControlLevel.Editor, DashboardPrivilegeLevel.CanView, true],
            ['v2', AccessControlLevel.Viewer, DashboardPrivilegeLevel.CanEdit, false],
        ] as const)(
            'with %s, RBAC %s, and dashboard privilege %s returns %s',
            (accessControlVersion, userAccessLevel, effectivePrivilegeLevel, expected) => {
                expect(
                    canEditDashboard({
                        access_control_version: accessControlVersion,
                        user_access_level: userAccessLevel,
                        effective_privilege_level: effectivePrivilegeLevel,
                    })
                ).toBe(expected)
            }
        )

        it('uses RBAC when the access control version is absent', () => {
            expect(canEditDashboard({ user_access_level: AccessControlLevel.Editor })).toBe(true)
            expect(canEditDashboard({ user_access_level: AccessControlLevel.Viewer })).toBe(false)
        })

        it('denies V1 editing when the dashboard privilege is absent', () => {
            expect(
                canEditDashboard({
                    access_control_version: 'v1',
                    user_access_level: AccessControlLevel.Editor,
                })
            ).toBe(false)
        })
    })
})
