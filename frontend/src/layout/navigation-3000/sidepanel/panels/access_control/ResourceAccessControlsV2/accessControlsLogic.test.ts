import { APIScopeObject, AccessControlLevel, EffectiveAccessControlEntry } from '~/types'

import { getLevelOptionsForResource } from './helpers'
import { AccessControlFilters, AccessControlMemberEntry, AccessControlRoleEntry } from './types'

function getEffectiveLevel(
    entry: { project: EffectiveAccessControlEntry; resources: Record<string, EffectiveAccessControlEntry> },
    resourceKey: APIScopeObject
): AccessControlLevel | null {
    if (resourceKey === 'project') {
        return entry.project.effective_access_level ?? null
    }
    return entry.resources[resourceKey]?.effective_access_level ?? null
}

function matchesFilters(
    entry: { project: EffectiveAccessControlEntry; resources: Record<string, EffectiveAccessControlEntry> },
    filters: AccessControlFilters
): boolean {
    const hasResourceFilter = filters.resourceKeys.length > 0
    const hasLevelFilter = filters.ruleLevels.length > 0

    if (hasResourceFilter && hasLevelFilter) {
        // Intersection: at least one selected resource must have one of the selected levels
        return filters.resourceKeys.some((rk) => {
            const level = getEffectiveLevel(entry, rk)
            return level !== null && (filters.ruleLevels as string[]).includes(level)
        })
    }

    if (hasResourceFilter) {
        return filters.resourceKeys.some((rk) => getEffectiveLevel(entry, rk) !== null)
    }

    if (hasLevelFilter) {
        const allKeys = ['project', ...Object.keys(entry.resources)] as APIScopeObject[]
        return filters.ruleLevels.some((rl) => allKeys.some((k) => getEffectiveLevel(entry, k) === rl))
    }

    return true
}

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

const emptyFilters: AccessControlFilters = {
    roleIds: [],
    memberIds: [],
    resourceKeys: [],
    ruleLevels: [],
}

describe('accessControlsLogic', () => {
    describe('matchesFilters', () => {
        const roleEntry: AccessControlRoleEntry = {
            role_id: 'role-1',
            role_name: 'Engineer',
            project: makeEffectiveEntry(AccessControlLevel.Admin),
            resources: {
                dashboard: makeEffectiveEntry(AccessControlLevel.Editor),
                insight: makeEffectiveEntry(null),
            },
        }

        const memberEntry: AccessControlMemberEntry = {
            organization_membership_id: 'member-1',
            user: { uuid: 'u1', first_name: 'John Doe', email: 'john@example.com' },
            organization_level: 1,
            project: makeEffectiveEntry(AccessControlLevel.Member),
            resources: {
                insight: makeEffectiveEntry(AccessControlLevel.Manager),
                dashboard: makeEffectiveEntry(null),
            },
        }

        it('returns true when no filters are set', () => {
            expect(matchesFilters(roleEntry, emptyFilters)).toBe(true)
            expect(matchesFilters(memberEntry, emptyFilters)).toBe(true)
        })

        describe('resourceKeys filter', () => {
            it('matches entries with effective access to the filtered resource', () => {
                const filters = { ...emptyFilters, resourceKeys: ['dashboard' as APIScopeObject] }
                expect(matchesFilters(roleEntry, filters)).toBe(true)
            })

            it('rejects entries without effective access to the filtered resource', () => {
                const filters = { ...emptyFilters, resourceKeys: ['dashboard' as APIScopeObject] }
                expect(matchesFilters(memberEntry, filters)).toBe(false)
            })

            it('matches if any of multiple resourceKeys has effective access', () => {
                const filters = {
                    ...emptyFilters,
                    resourceKeys: ['dashboard' as APIScopeObject, 'insight' as APIScopeObject],
                }
                expect(matchesFilters(memberEntry, filters)).toBe(true)
            })

            it('matches project as a resourceKey', () => {
                const filters = { ...emptyFilters, resourceKeys: ['project' as APIScopeObject] }
                expect(matchesFilters(roleEntry, filters)).toBe(true)
            })
        })

        describe('ruleLevels filter', () => {
            it('matches entries with the specified access level on project', () => {
                const filters = { ...emptyFilters, ruleLevels: [AccessControlLevel.Admin] }
                expect(matchesFilters(roleEntry, filters)).toBe(true)
            })

            it('matches entries with the specified access level on a resource', () => {
                const filters = { ...emptyFilters, ruleLevels: [AccessControlLevel.Manager] }
                expect(matchesFilters(memberEntry, filters)).toBe(true)
            })

            it('rejects entries without the specified access level', () => {
                const filters = { ...emptyFilters, ruleLevels: [AccessControlLevel.Viewer] }
                expect(matchesFilters(roleEntry, filters)).toBe(false)
            })

            it('matches any of multiple ruleLevels', () => {
                const filters = {
                    ...emptyFilters,
                    ruleLevels: [AccessControlLevel.Viewer, AccessControlLevel.Editor],
                }
                expect(matchesFilters(roleEntry, filters)).toBe(true)
            })
        })

        describe('combined filters', () => {
            it.each([
                [
                    'matches when a selected resource has one of the selected levels',
                    {
                        ...emptyFilters,
                        resourceKeys: ['insight' as APIScopeObject],
                        ruleLevels: [AccessControlLevel.Manager],
                    },
                    memberEntry,
                    true,
                ],
                [
                    'rejects when no selected resource has any of the selected levels',
                    {
                        ...emptyFilters,
                        resourceKeys: ['dashboard' as APIScopeObject],
                        ruleLevels: [AccessControlLevel.Viewer],
                    },
                    roleEntry,
                    false,
                ],
                [
                    'matches when resource has effective access at the selected level',
                    {
                        ...emptyFilters,
                        resourceKeys: ['dashboard' as APIScopeObject],
                        ruleLevels: [AccessControlLevel.Editor],
                    },
                    roleEntry,
                    true,
                ],
                [
                    'rejects when resource has no effective access even if level exists elsewhere',
                    {
                        ...emptyFilters,
                        resourceKeys: ['insight' as APIScopeObject],
                        ruleLevels: [AccessControlLevel.Admin],
                    },
                    roleEntry,
                    false,
                ],
            ])('%s', (_desc, filters, entry, expected) => {
                expect(matchesFilters(entry, filters)).toBe(expected)
            })
        })
    })

    describe('getLevelOptionsForResource', () => {
        const resourceLevels = [
            AccessControlLevel.None,
            AccessControlLevel.Viewer,
            AccessControlLevel.Editor,
            AccessControlLevel.Manager,
        ]

        const projectLevels = [AccessControlLevel.None, AccessControlLevel.Member, AccessControlLevel.Admin]

        it('returns all levels as values', () => {
            expect(getLevelOptionsForResource(resourceLevels).map((o) => o.value)).toEqual(resourceLevels)
            expect(getLevelOptionsForResource(projectLevels).map((o) => o.value)).toEqual(projectLevels)
        })

        it('returns no disabled reasons without options', () => {
            expect(getLevelOptionsForResource(resourceLevels).every((o) => o.disabledReason === undefined)).toBe(true)
        })

        it('formats None as "None" and capitalizes others', () => {
            const result = getLevelOptionsForResource(resourceLevels)
            expect(result.find((o) => o.value === AccessControlLevel.None)?.label).toBe('None')
            expect(result.find((o) => o.value === AccessControlLevel.Viewer)?.label).toBe('Viewer')
        })

        it('disables levels below minimum and above maximum', () => {
            const result = getLevelOptionsForResource(resourceLevels, {
                minimum: AccessControlLevel.Viewer,
                maximum: AccessControlLevel.Editor,
                inheritedLevel: null,
                inheritedReason: null,
                resourceLabel: 'Dashboards',
            })

            expect(result.find((o) => o.value === AccessControlLevel.None)?.disabledReason).toBe(
                'Minimum level for Dashboards is Viewer'
            )
            expect(result.find((o) => o.value === AccessControlLevel.Viewer)?.disabledReason).toBeUndefined()
            expect(result.find((o) => o.value === AccessControlLevel.Editor)?.disabledReason).toBeUndefined()
            expect(result.find((o) => o.value === AccessControlLevel.Manager)?.disabledReason).toBe(
                'Maximum level for Dashboards is Editor'
            )
        })
    })
})
