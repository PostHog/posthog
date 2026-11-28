import { APIScopeObject, AccessControlLevel, EffectiveAccessControlEntry } from '~/types'

import { getAccessSummaryTags, inheritedReasonOf, parseAccessDeepLink } from './helpers'
import { AccessControlRoleEntry } from './types'

const makeEffectiveEntry = (
    level: AccessControlLevel | null,
    overrides?: Partial<EffectiveAccessControlEntry>
): EffectiveAccessControlEntry => ({
    access_level: level,
    effective_access_level: level,
    inherited_access: null,
    minimum: AccessControlLevel.None,
    maximum: AccessControlLevel.Manager,
    ...overrides,
})

describe('helpers', () => {
    describe('inheritedReasonOf', () => {
        // The wire carries provenance; the settings copy only distinguishes three situations. A
        // wrong mapping here shows a member the wrong explanation and can unlock an admin's row.
        it.each([
            ['org_admin', null, 'organization_admin'],
            ['resource', 'role', 'role_override'],
            ['resource', 'default', 'project_default'],
            ['object', 'default', 'project_default'],
            ['system_default', null, 'project_default'],
        ] as const)('%s / %s reads as %s', (source, subject, expected) => {
            const inherited: EffectiveAccessControlEntry['inherited_access'] = {
                access_level: AccessControlLevel.Editor,
                source,
                source_subject: subject,
                source_resource: 'dashboard' as APIScopeObject,
                source_resource_id: null,
            }
            expect(inheritedReasonOf(inherited)).toBe(expected)
        })

        it('has no reason when nothing is inherited', () => {
            expect(inheritedReasonOf(null)).toBeNull()
        })
    })

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

        it('keeps only the picked products, and drops the project tag, while the Product filter has a selection', () => {
            const visibleResources = new Set<APIScopeObject>(['dashboard', 'tracing', 'insight'])
            const filteredResources = new Set<APIScopeObject>(['tracing'])
            expect(getAccessSummaryTags(roleEntry, visibleResources, filteredResources)).toEqual([
                { resource: 'tracing', level: AccessControlLevel.Viewer },
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

describe('parseAccessDeepLink', () => {
    it.each([
        ['no deep link params', { other: 'x' }, null],
        [
            'a member link',
            { access_tab: 'members', access_member_id: 'm-1', other: 'x' },
            { tab: 'members', roleId: null, memberId: 'm-1', rest: { other: 'x' } },
        ],
        [
            'a role link',
            { access_tab: 'roles', access_role_id: 'r-1' },
            { tab: 'roles', roleId: 'r-1', memberId: null, rest: {} },
        ],
        [
            'a member id under another tab',
            { access_tab: 'defaults', access_member_id: 'm-1' },
            { tab: 'defaults', roleId: null, memberId: null, rest: {} },
        ],
        ['an unknown tab', { access_tab: 'nope' }, { tab: null, roleId: null, memberId: null, rest: {} }],
    ])('reads %s', (_case, searchParams, expected) => {
        expect(parseAccessDeepLink(searchParams)).toEqual(expected)
    })
})
