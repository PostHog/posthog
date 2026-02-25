import { APIScopeObject, AccessControlLevel, EffectiveAccessControlEntry } from '~/types'

import { getEntryId, getInheritedReasonTooltip, getLevelOptionsForResource, getMinLevelDisabledReason } from './helpers'
import { AccessControlMemberEntry, AccessControlRoleEntry, FormAccessLevel } from './types'

const makeEntry = (
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

const resourceLevels = [
    AccessControlLevel.None,
    AccessControlLevel.Viewer,
    AccessControlLevel.Editor,
    AccessControlLevel.Manager,
]

const projectLevels = [AccessControlLevel.None, AccessControlLevel.Member, AccessControlLevel.Admin]

describe('groupedAccessControlRuleModalLogic', () => {
    describe('getEntryId', () => {
        it('returns role_id for role entries', () => {
            const entry: AccessControlRoleEntry = {
                role_id: 'role-abc',
                role_name: 'Engineer',
                project: makeEntry(AccessControlLevel.Member),
                resources: {},
            }
            expect(getEntryId(entry)).toBe('role-abc')
        })

        it('returns organization_membership_id for member entries', () => {
            const entry: AccessControlMemberEntry = {
                organization_membership_id: 'member-xyz',
                user: { uuid: 'u1', first_name: 'Alice', email: 'alice@example.com' },
                organization_level: 1,
                project: makeEntry(AccessControlLevel.Member),
                resources: {},
            }
            expect(getEntryId(entry)).toBe('member-xyz')
        })
    })

    describe('getInheritedReasonTooltip', () => {
        it.each([
            ['project_default' as const, 'Based on project default permissions'],
            ['role_override' as const, 'Based on role permissions'],
            [null, undefined],
            ['organization_admin' as const, undefined],
        ])('reason=%s returns %s', (reason, expected) => {
            expect(getInheritedReasonTooltip(reason)).toBe(expected)
        })
    })

    describe('getMinLevelDisabledReason', () => {
        it('returns org admin reason when inherited reason is organization_admin', () => {
            expect(getMinLevelDisabledReason(null, 'organization_admin', null, 'dashboard')).toBe(
                'User is an organization admin'
            )
        })

        it('returns project default reason', () => {
            expect(getMinLevelDisabledReason(AccessControlLevel.Viewer, 'project_default', null, 'dashboard')).toBe(
                'Project default is Viewer'
            )
        })

        it('returns role override reason', () => {
            expect(getMinLevelDisabledReason(AccessControlLevel.Editor, 'role_override', null, 'dashboard')).toBe(
                'User has a role with Editor access'
            )
        })

        it('returns minimum level reason when no inherited level', () => {
            expect(getMinLevelDisabledReason(null, null, AccessControlLevel.Viewer, 'Dashboards')).toBe(
                'Minimum level for Dashboards is Viewer'
            )
        })

        it('returns undefined when nothing applies', () => {
            expect(getMinLevelDisabledReason(null, null, null, 'dashboard')).toBeUndefined()
        })
    })

    describe('isProjectLevelShowingInherited (selector logic)', () => {
        function isProjectLevelShowingInherited(
            formProjectLevel: FormAccessLevel,
            entry: { project: EffectiveAccessControlEntry }
        ): boolean {
            return (
                formProjectLevel === entry.project.inherited_access_level &&
                entry.project.inherited_access_level !== null
            )
        }

        it('returns true when form level matches non-null inherited level', () => {
            const entry = {
                project: makeEntry(AccessControlLevel.Member, {
                    inherited_access_level: AccessControlLevel.Member,
                    inherited_access_level_reason: 'project_default',
                }),
            }
            expect(isProjectLevelShowingInherited(AccessControlLevel.Member, entry)).toBe(true)
        })

        it('returns false when form level differs from inherited', () => {
            const entry = {
                project: makeEntry(AccessControlLevel.Admin, {
                    inherited_access_level: AccessControlLevel.Member,
                }),
            }
            expect(isProjectLevelShowingInherited(AccessControlLevel.Admin, entry)).toBe(false)
        })

        it('returns false when inherited level is null', () => {
            const entry = { project: makeEntry(AccessControlLevel.Member) }
            expect(isProjectLevelShowingInherited(AccessControlLevel.Member, entry)).toBe(false)
        })
    })

    describe('featuresDisabledReason (selector logic)', () => {
        function featuresDisabledReason(loading: boolean, canEdit: boolean, isOrgAdmin: boolean): string | undefined {
            if (loading) {
                return 'Loading...'
            }
            if (!canEdit) {
                return 'Cannot edit'
            }
            if (isOrgAdmin) {
                return 'User is an organization admin and has access to all features'
            }
            return undefined
        }

        it.each([
            [true, true, false, 'Loading...'],
            [false, false, false, 'Cannot edit'],
            [false, true, true, 'User is an organization admin and has access to all features'],
            [false, true, false, undefined],
        ])('loading=%s canEdit=%s isOrgAdmin=%s => %s', (loading, canEdit, isOrgAdmin, expected) => {
            expect(featuresDisabledReason(loading, canEdit, isOrgAdmin)).toBe(expected)
        })

        it('loading takes priority over canEdit and isOrgAdmin', () => {
            expect(featuresDisabledReason(true, false, true)).toBe('Loading...')
        })
    })

    describe('projectLevelOptions (selector logic)', () => {
        it('uses inherited_access_level as minimum when present', () => {
            const entry = {
                project: makeEntry(AccessControlLevel.Member, {
                    inherited_access_level: AccessControlLevel.Member,
                    inherited_access_level_reason: 'project_default',
                    minimum: AccessControlLevel.None,
                }),
            }
            const result = getLevelOptionsForResource(projectLevels, {
                minimum: entry.project.inherited_access_level ?? entry.project.minimum,
                disabledReason: getMinLevelDisabledReason(
                    entry.project.inherited_access_level,
                    entry.project.inherited_access_level_reason,
                    entry.project.minimum,
                    'project'
                ),
            })

            expect(result.find((o) => o.value === AccessControlLevel.None)?.disabledReason).toBe(
                'Project default is Member'
            )
            expect(result.find((o) => o.value === AccessControlLevel.Member)?.disabledReason).toBeUndefined()
            expect(result.find((o) => o.value === AccessControlLevel.Admin)?.disabledReason).toBeUndefined()
        })

        it('falls back to minimum when no inherited level', () => {
            const entry = {
                project: makeEntry(AccessControlLevel.Member, {
                    minimum: AccessControlLevel.Member,
                }),
            }
            const result = getLevelOptionsForResource(projectLevels, {
                minimum: entry.project.inherited_access_level ?? entry.project.minimum,
                disabledReason: getMinLevelDisabledReason(
                    entry.project.inherited_access_level,
                    entry.project.inherited_access_level_reason,
                    entry.project.minimum,
                    'project'
                ),
            })

            expect(result.find((o) => o.value === AccessControlLevel.None)?.disabledReason).toBe(
                'Minimum level for project is Member'
            )
        })
    })

    describe('resourceLevelOptions (selector logic)', () => {
        function computeResourceLevelOptions(
            availableResourceLevels: AccessControlLevel[],
            entry: { resources: Record<string, EffectiveAccessControlEntry> },
            formResourceLevels: Record<APIScopeObject, FormAccessLevel>,
            resource: APIScopeObject,
            resourceLabel: string
        ): { value: AccessControlLevel | null; label: string; disabledReason?: string }[] {
            const { access_level, inherited_access_level, inherited_access_level_reason, minimum, maximum } = entry
                .resources[resource] as EffectiveAccessControlEntry
            const levelOptions = getLevelOptionsForResource(availableResourceLevels, {
                minimum: inherited_access_level ?? minimum,
                maximum: maximum,
                disabledReason: getMinLevelDisabledReason(
                    inherited_access_level,
                    inherited_access_level_reason,
                    minimum,
                    resourceLabel
                ),
            })
            const hasFormOverride = formResourceLevels[resource] !== null
            const hasSavedOverride = access_level !== null && formResourceLevels[resource] !== null
            if (inherited_access_level === null && (hasSavedOverride || hasFormOverride)) {
                return [{ value: null as AccessControlLevel | null, label: 'No override' }, ...levelOptions]
            }
            return levelOptions
        }

        it('returns level options with min/max constraints from entry', () => {
            const entry = {
                resources: {
                    dashboard: makeEntry(AccessControlLevel.Editor, {
                        inherited_access_level: AccessControlLevel.Viewer,
                        inherited_access_level_reason: 'project_default',
                        maximum: AccessControlLevel.Editor,
                    }),
                },
            }
            const formLevels = { dashboard: AccessControlLevel.Editor } as Record<APIScopeObject, FormAccessLevel>

            const result = computeResourceLevelOptions(
                resourceLevels,
                entry,
                formLevels,
                'dashboard' as APIScopeObject,
                'Dashboards'
            )

            expect(result.find((o) => o.value === AccessControlLevel.None)?.disabledReason).toBe(
                'Project default is Viewer'
            )
            expect(result.find((o) => o.value === AccessControlLevel.Manager)?.disabledReason).toBe(
                'Project default is Viewer'
            )
            expect(result.find((o) => o.value === AccessControlLevel.Viewer)?.disabledReason).toBeUndefined()
            expect(result.find((o) => o.value === AccessControlLevel.Editor)?.disabledReason).toBeUndefined()
        })

        it('prepends "No override" when no inherited level and form has override', () => {
            const entry = {
                resources: {
                    dashboard: makeEntry(null, {
                        access_level: null,
                    }),
                },
            }
            const formLevels = { dashboard: AccessControlLevel.Viewer } as Record<APIScopeObject, FormAccessLevel>

            const result = computeResourceLevelOptions(
                resourceLevels,
                entry,
                formLevels,
                'dashboard' as APIScopeObject,
                'Dashboards'
            )

            expect(result[0]).toEqual({ value: null, label: 'No override' })
            expect(result.length).toBe(resourceLevels.length + 1)
        })

        it('prepends "No override" when there is a saved override', () => {
            const entry = {
                resources: {
                    dashboard: makeEntry(AccessControlLevel.Editor, {
                        access_level: AccessControlLevel.Editor,
                    }),
                },
            }
            const formLevels = { dashboard: AccessControlLevel.Editor } as Record<APIScopeObject, FormAccessLevel>

            const result = computeResourceLevelOptions(
                resourceLevels,
                entry,
                formLevels,
                'dashboard' as APIScopeObject,
                'Dashboards'
            )

            expect(result[0]).toEqual({ value: null, label: 'No override' })
        })

        it('does not prepend "No override" when inherited level exists', () => {
            const entry = {
                resources: {
                    dashboard: makeEntry(AccessControlLevel.Viewer, {
                        inherited_access_level: AccessControlLevel.Viewer,
                        inherited_access_level_reason: 'project_default',
                    }),
                },
            }
            const formLevels = { dashboard: AccessControlLevel.Viewer } as Record<APIScopeObject, FormAccessLevel>

            const result = computeResourceLevelOptions(
                resourceLevels,
                entry,
                formLevels,
                'dashboard' as APIScopeObject,
                'Dashboards'
            )

            expect(result[0].value).not.toBeNull()
            expect(result.length).toBe(resourceLevels.length)
        })

        it('does not prepend "No override" when form level is null and no saved override', () => {
            const entry = {
                resources: {
                    dashboard: makeEntry(null, {
                        access_level: null,
                    }),
                },
            }
            const formLevels = { dashboard: null } as Record<APIScopeObject, FormAccessLevel>

            const result = computeResourceLevelOptions(
                resourceLevels,
                entry,
                formLevels,
                'dashboard' as APIScopeObject,
                'Dashboards'
            )

            expect(result.length).toBe(resourceLevels.length)
            expect(result[0].value).not.toBeNull()
        })
    })

    describe('showResourceAddOverrideButton (selector logic)', () => {
        it('returns true when displayed level is null', () => {
            const formResourceLevels = { dashboard: null } as Record<APIScopeObject, FormAccessLevel>
            const displayedLevel = formResourceLevels['dashboard' as APIScopeObject] ?? null
            expect(displayedLevel === null).toBe(true)
        })

        it('returns false when displayed level is set', () => {
            const formResourceLevels = { dashboard: AccessControlLevel.Editor } as Record<
                APIScopeObject,
                FormAccessLevel
            >
            const displayedLevel = formResourceLevels['dashboard' as APIScopeObject] ?? null
            expect(displayedLevel === null).toBe(false)
        })
    })

    describe('clearResourceOverrides (listener logic)', () => {
        function computeClearedLevels(
            resources: Record<string, EffectiveAccessControlEntry>
        ): Record<string, AccessControlLevel | null> {
            return Object.fromEntries(
                Object.entries(resources).map(([key, data]) => [key, data.inherited_access_level])
            )
        }

        it('resets only resources without inherited access level', () => {
            const resources = {
                dashboard: makeEntry(AccessControlLevel.Editor, {
                    inherited_access_level: AccessControlLevel.Viewer,
                    inherited_access_level_reason: 'project_default',
                }),
                insight: makeEntry(AccessControlLevel.Manager),
                action: makeEntry(AccessControlLevel.None, {
                    inherited_access_level: AccessControlLevel.None,
                    inherited_access_level_reason: 'role_override',
                }),
            }
            const result = computeClearedLevels(resources)
            expect(result).toEqual({
                dashboard: AccessControlLevel.Viewer,
                insight: null,
                action: AccessControlLevel.None,
            })
        })
    })

    describe('isResourceLevelShowingInherited (selector logic)', () => {
        function isResourceLevelShowingInherited(
            displayedLevel: AccessControlLevel | null,
            resourceEntry: EffectiveAccessControlEntry
        ): boolean {
            return (
                displayedLevel === resourceEntry.inherited_access_level && resourceEntry.inherited_access_level !== null
            )
        }

        it('returns true when displayed matches non-null inherited', () => {
            const entry = makeEntry(AccessControlLevel.Viewer, {
                inherited_access_level: AccessControlLevel.Viewer,
                inherited_access_level_reason: 'project_default',
            })
            expect(isResourceLevelShowingInherited(AccessControlLevel.Viewer, entry)).toBe(true)
        })

        it('returns false when displayed differs from inherited', () => {
            const entry = makeEntry(AccessControlLevel.Editor, {
                inherited_access_level: AccessControlLevel.Viewer,
            })
            expect(isResourceLevelShowingInherited(AccessControlLevel.Editor, entry)).toBe(false)
        })

        it('returns false when inherited is null', () => {
            const entry = makeEntry(AccessControlLevel.Viewer)
            expect(isResourceLevelShowingInherited(AccessControlLevel.Viewer, entry)).toBe(false)
        })
    })
})
