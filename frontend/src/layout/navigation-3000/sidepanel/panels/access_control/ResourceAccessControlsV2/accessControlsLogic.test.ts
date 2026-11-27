import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { APIScopeObject, AccessControlLevel, EffectiveAccessControlEntry, SidePanelTab } from '~/types'

import { accessControlLogic } from '../accessControlLogic'
import { resourcesAccessControlLogic } from '../resourcesAccessControlLogic'
import { accessControlsLogic } from './accessControlsLogic'
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
    inherited_access: null,
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

        it('formats None as "No access" and capitalizes others', () => {
            const result = getLevelOptionsForResource(resourceLevels)
            expect(result.find((o) => o.value === AccessControlLevel.None)?.label).toBe('No access')
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

    describe('panel entry loading', () => {
        let logic: ReturnType<typeof accessControlsLogic.build>

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:id/access_control_members': {
                        results: [
                            {
                                organization_membership_id: 'member-1',
                                user: { uuid: 'u1', first_name: 'John', email: 'john@example.com' },
                                organization_level: 1,
                                project: makeEffectiveEntry(AccessControlLevel.Member),
                                resources: {},
                            },
                        ],
                    },
                },
            })
            initKeaTests()
            logic = accessControlsLogic.build({ projectId: '997' })
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        it('reloads the entry when the already-open subject is opened again', async () => {
            // A member row click dispatches both of these (AccessControls.tsx)
            const clickMemberRow = (): void => {
                logic.actions.openAccessDetail('member', 'member-1')
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.AccessDetail, 'member:member-1')
            }

            await expectLogic(logic, clickMemberRow)
                .toDispatchActions(['loadPanelEntry', 'loadPanelEntrySuccess'])
                .toMatchValues({ panelEntry: partial({ organization_membership_id: 'member-1' }) })

            // Re-clicking the open row nulls the entry without changing the subject or the panel
            // options: the reload must fire again or the panel is stuck on "not found"
            await expectLogic(logic, clickMemberRow)
                .toDispatchActions(['loadPanelEntry', 'loadPanelEntrySuccess'])
                .toMatchValues({ panelEntry: partial({ organization_membership_id: 'member-1' }) })
        })
    })
    describe('deep links', () => {
        let logic: ReturnType<typeof accessControlsLogic.build>
        const settingsPath = '/project/997/settings/environment-access-control'

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:id/access_control_members': { results: [] },
                    '/api/projects/:id/access_control_roles': { results: [] },
                },
            })
            initKeaTests()
            logic = accessControlsLogic.build({ projectId: '997' })
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        it('opens the member once and drops the deep link params', async () => {
            router.actions.push(settingsPath, { access_tab: 'members', access_member_id: 'member-1' })

            await expectLogic(logic).toMatchValues({
                activeTab: 'members',
                activePanelSubject: { scopeType: 'member', subjectId: 'member-1' },
            })
            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
            expect(router.values.searchParams).toEqual({})
            expect(router.values.hashParams).toEqual({ panel: 'access-detail:member:member-1' })
        })

        it('lets the deep-linked panel close and stay closed', async () => {
            router.actions.push(settingsPath, { access_tab: 'members', access_member_id: 'member-1' })

            sidePanelStateLogic.actions.closeSidePanel()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
            expect(router.values.hashParams).toEqual({})
        })

        it('lets another member replace the deep-linked one', async () => {
            router.actions.push(settingsPath, { access_tab: 'members', access_member_id: 'member-1' })

            logic.actions.openAccessDetail('member', 'member-2')
            sidePanelStateLogic.actions.openSidePanel(SidePanelTab.AccessDetail, 'member:member-2')

            await expectLogic(logic).toMatchValues({
                activePanelSubject: { scopeType: 'member', subjectId: 'member-2' },
            })
            expect(router.values.hashParams).toEqual({ panel: 'access-detail:member:member-2' })
        })

        it('shows the member picked in the dialog over a stale panel link', async () => {
            featureFlagLogic.actions.setFeatureFlags(
                [FEATURE_FLAGS.ACCESS_CONTROL_DETAIL_PANEL, FEATURE_FLAGS.TODAY_RAIL_NAV],
                { [FEATURE_FLAGS.ACCESS_CONTROL_DETAIL_PANEL]: true, [FEATURE_FLAGS.TODAY_RAIL_NAV]: true }
            )
            sidePanelStateLogic.actions.openSidePanel(SidePanelTab.AccessDetail, 'member:member-1')

            logic.actions.openAccessDetail('member', 'member-2')

            await expectLogic(logic).toMatchValues({
                activePanelSubject: { scopeType: 'member', subjectId: 'member-2' },
            })
        })

        it('keeps a tab the user picked after a deep link', async () => {
            router.actions.push(settingsPath, { access_tab: 'members' })

            logic.actions.setActiveTab('defaults')
            sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support)

            await expectLogic(logic).toMatchValues({ activeTab: 'defaults' })
        })
    })

    describe('subject access changes', () => {
        let logic: ReturnType<typeof accessControlsLogic.build>

        beforeEach(() => {
            initKeaTests()
            logic = accessControlsLogic.build({ projectId: '997' })
            logic.mount()
        })

        afterEach(async () => {
            await expectLogic(
                accessControlLogic({ resource: 'project', resource_id: '997', title: '', description: '' })
            ).toFinishAllListeners()
            await expectLogic(resourcesAccessControlLogic).toFinishAllListeners()
            logic.unmount()
        })

        it('saves a role or member project rule through its own endpoint', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSubjectProjectAccess('role', 'role-1', AccessControlLevel.Admin)
                logic.actions.setSubjectProjectAccess('member', 'member-1', null)
            }).toDispatchActions([
                logic.actionCreators.updateAccessControlRoles(
                    [{ role: 'role-1', level: AccessControlLevel.Admin }],
                    'v2'
                ),
                logic.actionCreators.updateAccessControlMembers([{ member: 'member-1', level: null }], 'v2'),
            ])
        })

        it.each([
            ['role', { role: 'subject-1', organization_member: null }],
            ['member', { role: null, organization_member: 'subject-1' }],
        ] as const)('scopes a %s product rule to that subject', async (scopeType, subject) => {
            await expectLogic(logic, () => {
                logic.actions.setSubjectResourceAccess(scopeType, 'subject-1', 'dashboard', AccessControlLevel.Viewer)
            }).toDispatchActions([
                logic.actionCreators.updateResourceAccessControls(
                    [{ resource: 'dashboard', access_level: AccessControlLevel.Viewer, ...subject }],
                    scopeType
                ),
            ])
        })
    })
})
