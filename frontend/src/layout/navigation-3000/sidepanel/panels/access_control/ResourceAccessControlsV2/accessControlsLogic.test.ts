import { APIScopeObject, AccessControlLevel } from '~/types'

import { AccessControlLevelMapping } from './accessControlsLogic'
import { AccessControlFilters, AccessControlRow, AccessControlsTab } from './types'

/**
 * Pure function extracted from filteredSortedRows selector for testing.
 * Filters and returns rows based on tab, search text, filters, and role permissions.
 */
export function filteredSortedRows(
    activeTab: AccessControlsTab,
    allRows: AccessControlRow[],
    searchText: string,
    filters: AccessControlFilters,
    canUseRoles: boolean
): AccessControlRow[] {
    const search = searchText.trim().toLowerCase()

    return allRows.filter((row) => {
        if (activeTab === 'defaults') {
            return row.id === 'default'
        }
        if (activeTab === 'roles') {
            if (!canUseRoles || !row.id.startsWith('role:')) {
                return false
            }
            if (filters.roleIds.length > 0 && !filters.roleIds.includes(row.role.id)) {
                return false
            }
        }
        if (activeTab === 'members') {
            if (!row.id.startsWith('member:')) {
                return false
            }
            if (filters.memberIds.length > 0 && !filters.memberIds.includes(row.role.id)) {
                return false
            }
        }

        if (filters.resourceKeys.length > 0 && !row.levels.some((l) => filters.resourceKeys.includes(l.resourceKey))) {
            return false
        }

        if (filters.ruleLevels.length > 0 && !row.levels.some((l) => filters.ruleLevels.includes(l.level))) {
            return false
        }

        if (search.length > 0) {
            if (!row.role.name.toLowerCase().includes(search)) {
                return false
            }
        }

        return true
    })
}

/**
 * Pure function extracted from getLevelOptionsForResource selector for testing.
 * Returns available access level options with disabled reasons for min/max validation.
 */
export function getLevelOptionsForResource(
    projectAvailableLevels: AccessControlLevel[],
    resourceAvailableLevels: AccessControlLevel[],
    resourceKey: APIScopeObject,
    getMinimumAccessLevel: (resource: APIScopeObject) => AccessControlLevel | null,
    getMaximumAccessLevel: (resource: APIScopeObject) => AccessControlLevel | null
): { value: AccessControlLevel; label: string; disabledReason?: string }[] {
    const availableLevels = resourceKey === 'project' ? projectAvailableLevels : resourceAvailableLevels
    const uniqueLevels = Array.from(new Set(availableLevels))
    const minimumLevel = resourceKey === 'project' ? null : getMinimumAccessLevel(resourceKey)
    const maximumLevel = resourceKey === 'project' ? null : getMaximumAccessLevel(resourceKey)
    const minimumIndex = minimumLevel ? uniqueLevels.indexOf(minimumLevel) : null
    const maximumIndex = maximumLevel ? uniqueLevels.indexOf(maximumLevel) : null

    return uniqueLevels.map((level, index) => {
        const isBelowMinimum = minimumIndex !== null && minimumIndex !== -1 ? index < minimumIndex : false
        const isAboveMaximum = maximumIndex !== null && maximumIndex !== -1 ? index > maximumIndex : false
        const isDisabled = isBelowMinimum || isAboveMaximum

        return {
            value: level,
            label: level === AccessControlLevel.None ? 'None' : level.charAt(0).toUpperCase() + level.slice(1),
            disabledReason: isDisabled ? 'Not available for this feature' : undefined,
        }
    })
}

/**
 * Pure function extracted from saveGroupedRules listener for testing permission diffing.
 * Computes the diff between current and new access control levels.
 */
export function computeAccessControlDiff(
    currentLevels: AccessControlLevelMapping[],
    newLevels: AccessControlLevelMapping[]
): { resource: APIScopeObject; level: AccessControlLevel | null }[] {
    const currentLevelsMap = new Map(currentLevels.map((l) => [l.resourceKey, l.level]))
    const newLevelsMap = new Map(newLevels.map((l) => [l.resourceKey, l.level]))

    const updates: { resource: APIScopeObject; level: AccessControlLevel | null }[] = []

    // Check existing rules that might need to be deleted
    for (const resourceKey of currentLevelsMap.keys()) {
        if (!newLevelsMap.has(resourceKey)) {
            updates.push({ resource: resourceKey, level: null })
        }
    }

    // Add new or updated rules
    for (const [resourceKey, level] of newLevelsMap.entries()) {
        if (currentLevelsMap.get(resourceKey) !== level) {
            updates.push({ resource: resourceKey, level: level as AccessControlLevel | null })
        }
    }

    return updates
}

describe('accessControlsLogic', () => {
    describe('filteredSortedRows', () => {
        const defaultRow: AccessControlRow = {
            id: 'default',
            role: { id: 'default', name: 'Default' },
            levels: [{ resourceKey: 'project', level: AccessControlLevel.Member }],
        }

        const roleRow1: AccessControlRow = {
            id: 'role:role-1',
            role: { id: 'role-1', name: 'Engineer' },
            levels: [
                { resourceKey: 'project', level: AccessControlLevel.Admin },
                { resourceKey: 'dashboard', level: AccessControlLevel.Editor },
            ],
        }

        const roleRow2: AccessControlRow = {
            id: 'role:role-2',
            role: { id: 'role-2', name: 'Viewer' },
            levels: [{ resourceKey: 'project', level: AccessControlLevel.Viewer }],
        }

        const memberRow1: AccessControlRow = {
            id: 'member:member-1',
            role: { id: 'member-1', name: 'John Doe' },
            levels: [
                { resourceKey: 'project', level: AccessControlLevel.Member },
                { resourceKey: 'insight', level: AccessControlLevel.Manager },
            ],
        }

        const memberRow2: AccessControlRow = {
            id: 'member:member-2',
            role: { id: 'member-2', name: 'Jane Smith' },
            levels: [{ resourceKey: 'project', level: AccessControlLevel.Admin }],
        }

        const allRows = [defaultRow, roleRow1, roleRow2, memberRow1, memberRow2]

        const emptyFilters: AccessControlFilters = {
            roleIds: [],
            memberIds: [],
            resourceKeys: [],
            ruleLevels: [],
        }

        describe('tab filtering', () => {
            it('returns only default row when on defaults tab', () => {
                const result = filteredSortedRows('defaults', allRows, '', emptyFilters, true)
                expect(result).toEqual([defaultRow])
            })

            it('returns only role rows when on roles tab with canUseRoles=true', () => {
                const result = filteredSortedRows('roles', allRows, '', emptyFilters, true)
                expect(result).toEqual([roleRow1, roleRow2])
            })

            it('returns empty when on roles tab with canUseRoles=false', () => {
                const result = filteredSortedRows('roles', allRows, '', emptyFilters, false)
                expect(result).toEqual([])
            })

            it('returns only member rows when on members tab', () => {
                const result = filteredSortedRows('members', allRows, '', emptyFilters, true)
                expect(result).toEqual([memberRow1, memberRow2])
            })
        })

        describe('search filtering', () => {
            it('filters members by name (case insensitive)', () => {
                const result = filteredSortedRows('members', allRows, 'john', emptyFilters, true)
                expect(result).toEqual([memberRow1])
            })

            it('filters roles by name (case insensitive)', () => {
                const result = filteredSortedRows('roles', allRows, 'ENGINEER', emptyFilters, true)
                expect(result).toEqual([roleRow1])
            })

            it('returns empty when search matches nothing', () => {
                const result = filteredSortedRows('members', allRows, 'nonexistent', emptyFilters, true)
                expect(result).toEqual([])
            })

            it('trims whitespace from search text', () => {
                const result = filteredSortedRows('members', allRows, '  jane  ', emptyFilters, true)
                expect(result).toEqual([memberRow2])
            })
        })

        describe('roleIds filter', () => {
            it('filters roles by specific roleIds', () => {
                const filters = { ...emptyFilters, roleIds: ['role-1'] }
                const result = filteredSortedRows('roles', allRows, '', filters, true)
                expect(result).toEqual([roleRow1])
            })

            it('allows multiple roleIds', () => {
                const filters = { ...emptyFilters, roleIds: ['role-1', 'role-2'] }
                const result = filteredSortedRows('roles', allRows, '', filters, true)
                expect(result).toEqual([roleRow1, roleRow2])
            })
        })

        describe('memberIds filter', () => {
            it('filters members by specific memberIds', () => {
                const filters = { ...emptyFilters, memberIds: ['member-2'] }
                const result = filteredSortedRows('members', allRows, '', filters, true)
                expect(result).toEqual([memberRow2])
            })
        })

        describe('resourceKeys filter', () => {
            it('filters by rows that have specified resource', () => {
                const filters = { ...emptyFilters, resourceKeys: ['dashboard' as APIScopeObject] }
                const result = filteredSortedRows('roles', allRows, '', filters, true)
                expect(result).toEqual([roleRow1])
            })

            it('filters by rows with insight resource', () => {
                const filters = { ...emptyFilters, resourceKeys: ['insight' as APIScopeObject] }
                const result = filteredSortedRows('members', allRows, '', filters, true)
                expect(result).toEqual([memberRow1])
            })

            it('matches any of multiple resourceKeys', () => {
                const filters = {
                    ...emptyFilters,
                    resourceKeys: ['dashboard' as APIScopeObject, 'insight' as APIScopeObject],
                }
                const result = filteredSortedRows('members', allRows, '', filters, true)
                expect(result).toEqual([memberRow1])
            })
        })

        describe('ruleLevels filter', () => {
            it('filters by rows that have specified access level', () => {
                const filters = { ...emptyFilters, ruleLevels: [AccessControlLevel.Manager] }
                const result = filteredSortedRows('members', allRows, '', filters, true)
                expect(result).toEqual([memberRow1])
            })

            it('matches any of multiple ruleLevels', () => {
                const filters = { ...emptyFilters, ruleLevels: [AccessControlLevel.Viewer, AccessControlLevel.Admin] }
                const result = filteredSortedRows('roles', allRows, '', filters, true)
                expect(result).toEqual([roleRow1, roleRow2])
            })
        })

        describe('multi-criteria filtering', () => {
            it('combines search and resourceKeys filter', () => {
                const filters = { ...emptyFilters, resourceKeys: ['insight' as APIScopeObject] }
                const result = filteredSortedRows('members', allRows, 'john', filters, true)
                expect(result).toEqual([memberRow1])
            })

            it('combines search and ruleLevels filter', () => {
                const filters = { ...emptyFilters, ruleLevels: [AccessControlLevel.Admin] }
                const result = filteredSortedRows('members', allRows, 'jane', filters, true)
                expect(result).toEqual([memberRow2])
            })

            it('returns empty when multi-criteria has no matches', () => {
                const filters = { ...emptyFilters, ruleLevels: [AccessControlLevel.Viewer] }
                const result = filteredSortedRows('members', allRows, 'john', filters, true)
                expect(result).toEqual([])
            })

            it('combines all filters together', () => {
                const filters = {
                    ...emptyFilters,
                    resourceKeys: ['project' as APIScopeObject],
                    ruleLevels: [AccessControlLevel.Admin],
                }
                const result = filteredSortedRows('roles', allRows, 'eng', filters, true)
                expect(result).toEqual([roleRow1])
            })
        })
    })

    describe('getLevelOptionsForResource', () => {
        const projectLevels = [AccessControlLevel.None, AccessControlLevel.Member, AccessControlLevel.Admin]
        const resourceLevels = [
            AccessControlLevel.None,
            AccessControlLevel.Viewer,
            AccessControlLevel.Editor,
            AccessControlLevel.Manager,
        ]

        const noMinMax = (): AccessControlLevel | null => null

        describe('project resource', () => {
            it('uses projectAvailableLevels for project resource', () => {
                const result = getLevelOptionsForResource(projectLevels, resourceLevels, 'project', noMinMax, noMinMax)
                expect(result.map((o) => o.value)).toEqual(projectLevels)
            })

            it('does not apply min/max restrictions for project', () => {
                const getMin = (): AccessControlLevel | null => AccessControlLevel.Viewer
                const getMax = (): AccessControlLevel | null => AccessControlLevel.Editor

                const result = getLevelOptionsForResource(projectLevels, resourceLevels, 'project', getMin, getMax)
                expect(result.every((o) => o.disabledReason === undefined)).toBe(true)
            })
        })

        describe('non-project resources', () => {
            it('uses resourceAvailableLevels for non-project resources', () => {
                const result = getLevelOptionsForResource(
                    projectLevels,
                    resourceLevels,
                    'dashboard',
                    noMinMax,
                    noMinMax
                )
                expect(result.map((o) => o.value)).toEqual(resourceLevels)
            })

            it('disables levels below minimum', () => {
                const getMin = (): AccessControlLevel | null => AccessControlLevel.Viewer

                const result = getLevelOptionsForResource(projectLevels, resourceLevels, 'action', getMin, noMinMax)

                const noneOption = result.find((o) => o.value === AccessControlLevel.None)
                expect(noneOption?.disabledReason).toBe('Not available for this feature')

                const viewerOption = result.find((o) => o.value === AccessControlLevel.Viewer)
                expect(viewerOption?.disabledReason).toBeUndefined()
            })

            it('disables levels above maximum', () => {
                const getMax = (): AccessControlLevel | null => AccessControlLevel.Viewer

                const result = getLevelOptionsForResource(
                    projectLevels,
                    resourceLevels,
                    'activity_log',
                    noMinMax,
                    getMax
                )

                const viewerOption = result.find((o) => o.value === AccessControlLevel.Viewer)
                expect(viewerOption?.disabledReason).toBeUndefined()

                const editorOption = result.find((o) => o.value === AccessControlLevel.Editor)
                expect(editorOption?.disabledReason).toBe('Not available for this feature')

                const managerOption = result.find((o) => o.value === AccessControlLevel.Manager)
                expect(managerOption?.disabledReason).toBe('Not available for this feature')
            })

            it('disables levels outside both min and max range', () => {
                const getMin = (): AccessControlLevel | null => AccessControlLevel.Viewer
                const getMax = (): AccessControlLevel | null => AccessControlLevel.Editor

                const result = getLevelOptionsForResource(projectLevels, resourceLevels, 'dashboard', getMin, getMax)

                expect(result.find((o) => o.value === AccessControlLevel.None)?.disabledReason).toBe(
                    'Not available for this feature'
                )
                expect(result.find((o) => o.value === AccessControlLevel.Viewer)?.disabledReason).toBeUndefined()
                expect(result.find((o) => o.value === AccessControlLevel.Editor)?.disabledReason).toBeUndefined()
                expect(result.find((o) => o.value === AccessControlLevel.Manager)?.disabledReason).toBe(
                    'Not available for this feature'
                )
            })
        })

        describe('label formatting', () => {
            it('formats None level as "None"', () => {
                const result = getLevelOptionsForResource(
                    [AccessControlLevel.None],
                    resourceLevels,
                    'project',
                    noMinMax,
                    noMinMax
                )
                expect(result[0].label).toBe('None')
            })

            it('capitalizes other level names', () => {
                const result = getLevelOptionsForResource(
                    projectLevels,
                    resourceLevels,
                    'dashboard',
                    noMinMax,
                    noMinMax
                )
                expect(result.find((o) => o.value === AccessControlLevel.Viewer)?.label).toBe('Viewer')
                expect(result.find((o) => o.value === AccessControlLevel.Editor)?.label).toBe('Editor')
            })
        })

        describe('deduplication', () => {
            it('removes duplicate levels', () => {
                const duplicateLevels = [
                    AccessControlLevel.Viewer,
                    AccessControlLevel.Editor,
                    AccessControlLevel.Viewer,
                    AccessControlLevel.Editor,
                ]

                const result = getLevelOptionsForResource(
                    projectLevels,
                    duplicateLevels,
                    'dashboard',
                    noMinMax,
                    noMinMax
                )
                expect(result.length).toBe(2)
            })
        })
    })

    describe('computeAccessControlDiff (saveGroupedRules logic)', () => {
        describe('detecting deletions', () => {
            it('marks removed resources as null', () => {
                const current: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Admin },
                    { resourceKey: 'dashboard', level: AccessControlLevel.Editor },
                ]
                const newLevels: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Admin },
                ]

                const diff = computeAccessControlDiff(current, newLevels)

                expect(diff).toContainEqual({ resource: 'dashboard', level: null })
            })

            it('marks multiple removed resources', () => {
                const current: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Admin },
                    { resourceKey: 'dashboard', level: AccessControlLevel.Editor },
                    { resourceKey: 'insight', level: AccessControlLevel.Manager },
                ]
                const newLevels: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Admin },
                ]

                const diff = computeAccessControlDiff(current, newLevels)

                expect(diff).toContainEqual({ resource: 'dashboard', level: null })
                expect(diff).toContainEqual({ resource: 'insight', level: null })
            })
        })

        describe('detecting additions', () => {
            it('includes new resources in diff', () => {
                const current: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Member },
                ]
                const newLevels: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Member },
                    { resourceKey: 'dashboard', level: AccessControlLevel.Editor },
                ]

                const diff = computeAccessControlDiff(current, newLevels)

                expect(diff).toContainEqual({ resource: 'dashboard', level: AccessControlLevel.Editor })
            })
        })

        describe('detecting updates', () => {
            it('includes changed levels in diff', () => {
                const current: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Member },
                    { resourceKey: 'dashboard', level: AccessControlLevel.Viewer },
                ]
                const newLevels: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Admin },
                    { resourceKey: 'dashboard', level: AccessControlLevel.Editor },
                ]

                const diff = computeAccessControlDiff(current, newLevels)

                expect(diff).toContainEqual({ resource: 'project', level: AccessControlLevel.Admin })
                expect(diff).toContainEqual({ resource: 'dashboard', level: AccessControlLevel.Editor })
            })

            it('excludes unchanged levels from diff', () => {
                const current: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Admin },
                    { resourceKey: 'dashboard', level: AccessControlLevel.Editor },
                ]
                const newLevels: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Admin },
                    { resourceKey: 'dashboard', level: AccessControlLevel.Editor },
                ]

                const diff = computeAccessControlDiff(current, newLevels)

                expect(diff).toEqual([])
            })
        })

        describe('combined operations', () => {
            it('handles additions, updates, and deletions together', () => {
                const current: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Member },
                    { resourceKey: 'dashboard', level: AccessControlLevel.Viewer },
                    { resourceKey: 'insight', level: AccessControlLevel.Editor },
                ]
                const newLevels: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Admin },
                    { resourceKey: 'dashboard', level: AccessControlLevel.Viewer },
                    { resourceKey: 'action', level: AccessControlLevel.Manager },
                ]

                const diff = computeAccessControlDiff(current, newLevels)

                expect(diff).toContainEqual({ resource: 'insight', level: null })
                expect(diff).toContainEqual({ resource: 'project', level: AccessControlLevel.Admin })
                expect(diff).toContainEqual({ resource: 'action', level: AccessControlLevel.Manager })
                expect(diff).not.toContainEqual(expect.objectContaining({ resource: 'dashboard' }))
            })

            it('returns empty diff when nothing changed', () => {
                const levels: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Admin },
                ]

                const diff = computeAccessControlDiff(levels, levels)

                expect(diff).toEqual([])
            })
        })

        describe('edge cases', () => {
            it('handles empty current levels', () => {
                const newLevels: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Admin },
                ]

                const diff = computeAccessControlDiff([], newLevels)

                expect(diff).toEqual([{ resource: 'project', level: AccessControlLevel.Admin }])
            })

            it('handles empty new levels', () => {
                const current: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: AccessControlLevel.Admin },
                ]

                const diff = computeAccessControlDiff(current, [])

                expect(diff).toEqual([{ resource: 'project', level: null }])
            })

            it('handles both empty', () => {
                const diff = computeAccessControlDiff([], [])
                expect(diff).toEqual([])
            })
        })
    })
})
