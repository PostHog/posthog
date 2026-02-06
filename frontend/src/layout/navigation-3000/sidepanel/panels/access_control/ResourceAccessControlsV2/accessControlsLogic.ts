import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { OrganizationMembershipLevel } from 'lib/constants'
import { fullName, toSentenceCase } from 'lib/utils'
import { getMaximumAccessLevel, getMinimumAccessLevel, pluralizeResource } from 'lib/utils/accessControlUtils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    APIScopeObject,
    AccessControlLevel,
    AccessControlType,
    AccessControlTypeMember,
    AccessControlTypeOrganizationAdmins,
    AvailableFeature,
    OrganizationMemberType,
} from '~/types'

import { accessControlLogic } from '../accessControlLogic'
import { MemberResourceAccessControls, resourcesAccessControlLogic } from '../resourcesAccessControlLogic'
import { roleAccessControlLogic } from '../roleAccessControlLogic'
import type { accessControlsLogicType } from './accessControlsLogicType'
import { getIdForDefaultRow, getIdForMemberRow, getIdForRoleRow } from './helpers'
import { AccessControlFilters, AccessControlRow, AccessControlsTab, RuleModalState, ScopeType } from './types'

export interface AccessControlsLogicProps {
    projectId: string
}

const initialFilters: AccessControlFilters = {
    roleIds: [],
    memberIds: [],
    resourceKeys: [],
    ruleLevels: [],
}

export type AccessControlLevelMapping = {
    resourceKey: APIScopeObject
    level: AccessControlLevel
}

export type GroupedAccessControlRulesForm = {
    scopeId: string | null
    levels: AccessControlLevelMapping[]
}

export const accessControlsLogic = kea<accessControlsLogicType>([
    path([
        'layout',
        'navigation-3000',
        'sidepanel',
        'panels',
        'access_control',
        'ResourceAccessControlsV2',
        'accessControlsLogic',
    ]),
    props({} as AccessControlsLogicProps),
    key((props) => props.projectId),
    connect((props: AccessControlsLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeam'],
            membersLogic,
            ['sortedMembers'],
            userLogic,
            ['hasAvailableFeature'],
            roleAccessControlLogic,
            ['roles'],
            resourcesAccessControlLogic,
            [
                'resourceAccessControlsLoading',
                'availableLevels as resourceAvailableLevels',
                'defaultResourceAccessControls',
                'memberResourceAccessControls',
                'roleResourceAccessControls',
                'resources',
                'canEditRoleBasedAccessControls',
            ],
            accessControlLogic({
                resource: 'project',
                resource_id: props.projectId,
                title: '',
                description: '',
            }),
            [
                'accessControlDefault',
                'accessControlRoles',
                'accessControlMembers',
                'availableLevelsWithNone as projectAvailableLevels',
                'canEditAccessControls',
                'accessControlsLoading',
            ],
        ],
        actions: [
            resourcesAccessControlLogic,
            ['updateResourceAccessControls'],
            accessControlLogic({
                resource: 'project',
                resource_id: props.projectId,
                title: '',
                description: '',
            }),
            ['updateAccessControlDefault', 'updateAccessControlMembers', 'updateAccessControlRoles'],
        ],
    })),

    actions({
        setActiveTab: (activeTab: AccessControlsTab) => ({ activeTab }),
        setFilters: (filters: Partial<AccessControlFilters>) => ({ filters }),
        setSearchText: (searchText: string) => ({ searchText }),
        openRuleModal: (state: RuleModalState) => ({ state }),
        closeRuleModal: true,
        saveGroupedRules: (params: {
            scopeType: ScopeType
            scopeId: string | null
            levels: AccessControlLevelMapping[]
        }) => params,
    }),

    reducers({
        activeTab: [
            'defaults' as AccessControlsTab,
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
        filters: [
            initialFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        searchText: [
            '',
            {
                setSearchText: (_, { searchText }) => searchText,
            },
        ],
        ruleModalState: [
            null as RuleModalState | null,
            {
                openRuleModal: (_: RuleModalState | null, { state }: { state: RuleModalState }) => state,
                closeRuleModal: () => null,
            },
        ],
    }),

    selectors({
        canUseRoles: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS),
        ],

        allMembers: [(s) => [s.sortedMembers], (sortedMembers): OrganizationMemberType[] => sortedMembers ?? []],

        resourcesWithProject: [
            (s) => [s.resources],
            (resources): { key: APIScopeObject; label: string }[] => {
                const resourcesList = resources as unknown as AccessControlType['resource'][]
                const resourceOptions = resourcesList.map((resource) => ({
                    key: resource,
                    label: toSentenceCase(pluralizeResource(resource)),
                }))
                return [{ key: 'project' as APIScopeObject, label: 'Project' }, ...resourceOptions]
            },
        ],

        projectDefaultLevel: [
            (s) => [s.accessControlDefault],
            (accessControlDefault): AccessControlLevel => accessControlDefault?.access_level ?? AccessControlLevel.None,
        ],

        allRows: [
            (s) => [
                s.canUseRoles,
                s.defaultResourceAccessControls,
                s.allMembers,
                s.projectDefaultLevel,
                s.accessControlMembers,
                s.accessControlRoles,
                s.memberResourceAccessControls,
                s.roleResourceAccessControls,
                s.roles,
            ],
            (
                canUseRoles,
                defaultResourceAccessControls,
                allMembers,
                projectDefaultLevel,
                accessControlMembers,
                accessControlRoles,
                memberResourceAccessControls,
                roleResourceAccessControls,
                roles
            ): AccessControlRow[] => {
                const resourcesList = defaultResourceAccessControls.accessControlByResource
                const rows: AccessControlRow[] = []

                // Default scope row
                const defaultLevels: AccessControlLevelMapping[] = [
                    { resourceKey: 'project', level: projectDefaultLevel as AccessControlLevel },
                ]
                for (const [resourceKey, control] of Object.entries(resourcesList)) {
                    if (control?.access_level !== null && control?.access_level !== undefined) {
                        defaultLevels.push({
                            resourceKey: resourceKey as APIScopeObject,
                            level: control.access_level as AccessControlLevel,
                        })
                    }
                }
                rows.push({
                    id: getIdForDefaultRow(),
                    role: { id: 'default', name: 'Default' },
                    levels: defaultLevels,
                })

                // Role scope rows
                if (canUseRoles) {
                    for (const role of roles ?? []) {
                        const levels: AccessControlLevelMapping[] = []
                        const projectOverride = accessControlRoles.find((o) => o.role === role.id)
                        levels.push({
                            resourceKey: 'project',
                            level: (projectOverride?.access_level ?? projectDefaultLevel) as AccessControlLevel,
                        })

                        const roleResourceEntry = roleResourceAccessControls.find((r) => r.role?.id === role.id)
                        if (roleResourceEntry) {
                            for (const [resourceKey, control] of Object.entries(
                                roleResourceEntry.accessControlByResource
                            )) {
                                if (control?.access_level !== null && control?.access_level !== undefined) {
                                    levels.push({
                                        resourceKey: resourceKey as APIScopeObject,
                                        level: control.access_level as AccessControlLevel,
                                    })
                                }
                            }
                        }
                        rows.push({
                            id: getIdForRoleRow(role.id),
                            role: { id: role.id, name: role.name },
                            levels,
                        })
                    }
                }

                // Member scope rows
                const mappedAccessControlMembers = accessControlMembers.reduce(
                    (acc, accessControlMember) => {
                        if (!accessControlMember.organization_member) {
                            return acc
                        }
                        return Object.assign(acc, { [accessControlMember.organization_member]: accessControlMember })
                    },
                    {} as Record<string, AccessControlTypeMember | AccessControlTypeOrganizationAdmins>
                )
                const mappedMemberResourceEntries = memberResourceAccessControls.reduce(
                    (acc, memberAccessControl) => {
                        if (!memberAccessControl.organization_member) {
                            return acc
                        }
                        return Object.assign(acc, {
                            [memberAccessControl.organization_member?.id]: memberAccessControl,
                        })
                    },
                    {} as Record<string, MemberResourceAccessControls>
                )

                for (const member of allMembers) {
                    const levels: AccessControlLevelMapping[] = []
                    const projectOverride = mappedAccessControlMembers[member.id]
                    const isOrgAdmin = member.level >= OrganizationMembershipLevel.Admin
                    // Org admins/owners always have admin access to the project
                    const effectiveProjectLevel = isOrgAdmin
                        ? AccessControlLevel.Admin
                        : ((projectOverride?.access_level ?? projectDefaultLevel) as AccessControlLevel)
                    levels.push({
                        resourceKey: 'project',
                        level: effectiveProjectLevel,
                    })

                    const memberResourceEntry = mappedMemberResourceEntries[member.id]
                    if (memberResourceEntry) {
                        for (const [resourceKey, control] of Object.entries(
                            memberResourceEntry.accessControlByResource
                        )) {
                            if (control?.access_level !== null && control?.access_level !== undefined) {
                                levels.push({
                                    resourceKey: resourceKey as APIScopeObject,
                                    level: control.access_level as AccessControlLevel,
                                })
                            }
                        }
                    }
                    rows.push({
                        id: getIdForMemberRow(member.id),
                        role: { id: member.id, name: fullName(member.user) },
                        member,
                        levels,
                    })
                }

                return rows
            },
        ],

        ruleOptions: [
            (s) => [s.projectAvailableLevels, s.resourceAvailableLevels],
            (projectAvailableLevels, resourceAvailableLevels): { key: string; label: string }[] => {
                const levelSet = new Set<string>()
                for (const level of projectAvailableLevels) {
                    levelSet.add(level)
                }
                for (const level of resourceAvailableLevels) {
                    levelSet.add(level)
                }
                levelSet.add(AccessControlLevel.None)

                return [...levelSet]
                    .sort((a, b) => a.localeCompare(b))
                    .map((level) => ({
                        key: level,
                        label: level === AccessControlLevel.None ? 'None' : toSentenceCase(level),
                    }))
            },
        ],

        getLevelOptionsForResource: [
            (s) => [s.projectAvailableLevels, s.resourceAvailableLevels],
            (
                projectAvailableLevels,
                resourceAvailableLevels
            ): ((
                resourceKey: APIScopeObject
            ) => { value: AccessControlLevel; label: string; disabledReason?: string }[]) => {
                return (
                    resourceKey: APIScopeObject
                ): { value: AccessControlLevel; label: string; disabledReason?: string }[] => {
                    const availableLevels = resourceKey === 'project' ? projectAvailableLevels : resourceAvailableLevels
                    const uniqueLevels = Array.from(new Set(availableLevels))
                    const minimumLevel = resourceKey === 'project' ? null : getMinimumAccessLevel(resourceKey)
                    const maximumLevel = resourceKey === 'project' ? null : getMaximumAccessLevel(resourceKey)
                    const minimumIndex = minimumLevel ? uniqueLevels.indexOf(minimumLevel) : null
                    const maximumIndex = maximumLevel ? uniqueLevels.indexOf(maximumLevel) : null

                    return uniqueLevels.map((level, index) => {
                        const isBelowMinimum =
                            minimumIndex !== null && minimumIndex !== -1 ? index < minimumIndex : false
                        const isAboveMaximum =
                            maximumIndex !== null && maximumIndex !== -1 ? index > maximumIndex : false
                        const isDisabled = isBelowMinimum || isAboveMaximum

                        return {
                            value: level,
                            label: level === AccessControlLevel.None ? 'None' : toSentenceCase(level),
                            disabledReason: isDisabled ? 'Not available for this feature' : undefined,
                        }
                    })
                }
            },
        ],

        filteredSortedRows: [
            (s) => [s.activeTab, s.allRows, s.searchText, s.filters, s.canUseRoles],
            (activeTab, allRows, searchText, filters, canUseRoles): AccessControlRow[] => {
                const search = searchText.trim().toLowerCase()

                const rows = allRows.filter((row) => {
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

                    if (
                        filters.resourceKeys.length > 0 &&
                        !row.levels.some((l) => filters.resourceKeys.includes(l.resourceKey))
                    ) {
                        return false
                    }

                    if (
                        filters.ruleLevels.length > 0 &&
                        !row.levels.some((l) => filters.ruleLevels.includes(l.level))
                    ) {
                        return false
                    }

                    if (search.length > 0) {
                        if (!row.role.name.toLowerCase().includes(search)) {
                            return false
                        }
                    }

                    return true
                })

                return rows
            },
        ],

        canEditAny: [
            (s) => [s.canEditAccessControls, s.canEditRoleBasedAccessControls],
            (canEditAccessControls, canEditRoleBasedAccessControls): boolean =>
                !!canEditAccessControls || !!canEditRoleBasedAccessControls,
        ],

        loading: [
            (s) => [s.resourceAccessControlsLoading, s.accessControlsLoading],
            (resourceAccessControlsLoading, accessControlsLoading): boolean =>
                resourceAccessControlsLoading || accessControlsLoading,
        ],

        ruleModalMemberIsOrgAdmin: [
            (s) => [s.ruleModalState],
            (ruleModalState): boolean => {
                if (!ruleModalState) {
                    return false
                }

                const row = ruleModalState.row
                if (!row.member) {
                    return false
                }

                return row.member.level >= OrganizationMembershipLevel.Admin
            },
        ],

        ruleModalMemberHasAdminAccess: [
            (s) => [s.ruleModalState, s.ruleModalMemberIsOrgAdmin],
            (ruleModalState, ruleModalMemberIsOrgAdmin): boolean => {
                if (!ruleModalState) {
                    return false
                }

                if (ruleModalMemberIsOrgAdmin) {
                    return true
                }

                const row = ruleModalState.row
                if (!row.member) {
                    return false
                }

                // Check if member has project admin access
                const projectLevel = row.levels.find((l) => l.resourceKey === 'project')
                if (projectLevel?.level === AccessControlLevel.Admin) {
                    return true
                }

                return false
            },
        ],

        ruleModalRoleHasAdminAccess: [
            (s) => [s.ruleModalState],
            (ruleModalState): boolean => {
                if (!ruleModalState) {
                    return false
                }

                const row = ruleModalState.row
                if (!row.role) {
                    return false
                }

                // Check if row has project admin access
                const projectLevel = row.levels.find((l) => l.resourceKey === 'project')
                if (projectLevel?.level === AccessControlLevel.Admin) {
                    return true
                }

                return false
            },
        ],
    }),
    forms(() => ({
        groupedRulesForm: {
            defaults: {
                scopeId: null,
                levels: [] as AccessControlLevelMapping[],
            } as GroupedAccessControlRulesForm,
        },
    })),

    listeners(({ actions, values }) => ({
        saveGroupedRules: async ({ scopeType, scopeId, levels }) => {
            const currentRow = values.allRows.find((row) => row.role.id === (scopeId ?? 'default'))

            const currentLevelsMap = new Map(currentRow?.levels.map((l) => [l.resourceKey, l.level]) || [])
            const newLevelsMap = new Map(levels.map((l) => [l.resourceKey, l.level]))

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

            const projectUpdate = updates.find((u) => u.resource === 'project')
            const otherUpdates = updates.filter((u) => u.resource !== 'project')

            if (projectUpdate) {
                if (scopeType === 'default') {
                    actions.updateAccessControlDefault(projectUpdate.level ?? AccessControlLevel.None)
                } else if (scopeType === 'role' && scopeId) {
                    actions.updateAccessControlRoles([{ role: scopeId, level: projectUpdate.level }])
                } else if (scopeType === 'member' && scopeId) {
                    actions.updateAccessControlMembers([{ member: scopeId, level: projectUpdate.level }])
                }
            }

            if (otherUpdates.length > 0) {
                actions.updateResourceAccessControls(
                    otherUpdates.map((u) => ({
                        resource: u.resource,
                        access_level: u.level,
                        role: scopeType === 'role' ? scopeId : null,
                        organization_member: scopeType === 'member' ? scopeId : null,
                    })),
                    scopeType
                )
            }

            actions.closeRuleModal()
        },
    })),
])
