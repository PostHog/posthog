import { APIScopeObject, AccessControlLevel, EffectiveAccessControlEntry } from '~/types'

import { getAccessSummaryTags } from './helpers'
import { AccessControlRoleEntry } from './types'

const makeEffectiveEntry = (
    level: AccessControlLevel | null,
    overrides?: Partial<EffectiveAccessControlEntry>
): EffectiveAccessControlEntry => ({
    access_level: level,
    effective_access_level: level,
    inherited_access_level: null,
    inherited_access_level_reason: null,
    minimum: AccessControlLevel.None,
    maximum: AccessControlLevel.Manager,
    ...overrides,
})

describe('helpers', () => {
    describe('getAccessSummaryTags', () => {
        const roleEntry: AccessControlRoleEntry = {
            role_id: 'role-1',
            role_name: 'Engineer',
            project: makeEffectiveEntry(AccessControlLevel.Admin),
            resources: {
                dashboard: makeEffectiveEntry(AccessControlLevel.Editor),
                tracing: makeEffectiveEntry(AccessControlLevel.Viewer),
                insight: makeEffectiveEntry(null),
            },
        }

        it('includes the project tag and visible resources with an effective access level', () => {
            const visibleResources = new Set<APIScopeObject>(['dashboard', 'tracing', 'insight'])
            expect(getAccessSummaryTags(roleEntry, visibleResources)).toEqual([
                { resource: 'project', level: AccessControlLevel.Admin },
                { resource: 'dashboard', level: AccessControlLevel.Editor },
                { resource: 'tracing', level: AccessControlLevel.Viewer },
            ])
        })

        it('omits a resource with an effective access level if its product is not rolled out', () => {
            const visibleResources = new Set<APIScopeObject>(['dashboard'])
            expect(getAccessSummaryTags(roleEntry, visibleResources)).toEqual([
                { resource: 'project', level: AccessControlLevel.Admin },
                { resource: 'dashboard', level: AccessControlLevel.Editor },
            ])
        })

        it('omits the project tag when there is no effective project access', () => {
            const entry = { ...roleEntry, project: makeEffectiveEntry(null) }
            const visibleResources = new Set<APIScopeObject>(['dashboard'])
            expect(getAccessSummaryTags(entry, visibleResources)).toEqual([
                { resource: 'dashboard', level: AccessControlLevel.Editor },
            ])
        })
    })
})
