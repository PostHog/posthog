import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { fullName, toSentenceCase } from 'lib/utils'
import { pluralizeResource } from 'lib/utils/accessControlUtils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    APIScopeObject,
    AccessControlLevel,
    AccessControlType,
    AccessControlTypeMember,
    AvailableFeature,
    OrganizationMemberType,
} from '~/types'

import { accessControlLogic } from '../accessControlLogic'
import { resourcesAccessControlLogic } from '../resourcesAccessControlLogic'
import { roleAccessControlLogic } from '../roleAccessControlLogic'
import type { accessControlsLogicType } from './accessControlsLogicType'
import { humanizeAccessControlLevel, scopeTypeForAccessControlsTab, sortAccessControlRows } from './helpers'
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
        deleteRule: (row: AccessControlRow) => ({ row }),
        saveRule: (params: {
            scopeType: ScopeType
            scopeId: string | null
            resourceKey: APIScopeObject
            level: AccessControlLevel
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
                openRuleModal: (_: RuleModalState | null, { state }: { state: RuleModalState }) =>
                    state as RuleModalState,
                closeRuleModal: () => null as null,
            },
        ],
    }),

    selectors({
        canUseRoles: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS),
        ],

        allMembers: [(s) => [s.sortedMembers], (sortedMembers): OrganizationMemberType[] => sortedMembers ?? []],

        projectResourceLabel: [
            (s) => [s.currentTeam],
            (currentTeam): string => {
                const projectName = currentTeam?.name ?? 'Untitled'
                return `Project (${projectName})`
            },
        ],

        resourcesWithProject: [
            (s) => [s.resources, s.projectResourceLabel],
            (resources, projectResourceLabel): { key: APIScopeObject; label: string }[] => {
                const resourcesList = resources as unknown as AccessControlType['resource'][]
                const resourceOptions = resourcesList.map((resource) => ({
                    key: resource as APIScopeObject,
                    label: toSentenceCase(pluralizeResource(resource as APIScopeObject)),
                }))
                return [{ key: 'project' as APIScopeObject, label: projectResourceLabel }, ...resourceOptions]
            },
        ],

        projectDefaultLevel: [
            (s) => [s.accessControlDefault],
            (accessControlDefault): AccessControlLevel => accessControlDefault?.access_level ?? AccessControlLevel.None,
        ],

        projectRoleOverrideByRoleId: [
            (s) => [s.accessControlRoles],
            (accessControlRoles): Map<string, AccessControlLevel> =>
                new Map(accessControlRoles.map((ac) => [ac.role, ac.access_level ?? AccessControlLevel.None])),
        ],

        projectMemberOverrideByMemberId: [
            (s) => [s.accessControlMembers],
            (accessControlMembers): Map<string, AccessControlLevel> =>
                new Map(
                    (accessControlMembers as (AccessControlTypeMember | any)[])
                        .filter(
                            (ac): ac is AccessControlTypeMember => !!(ac as AccessControlTypeMember).organization_member
                        )
                        .map((ac) => [ac.organization_member as string, ac.access_level as AccessControlLevel])
                ),
        ],

        resourceRoleOverrideByRoleIdAndResourceKey: [
            (s) => [s.roleResourceAccessControls],
            (roleResourceAccessControls): Map<string, Map<string, AccessControlLevel>> => {
                const out = new Map<string, Map<string, AccessControlLevel>>()
                for (const entry of roleResourceAccessControls) {
                    if (!entry.role) {
                        continue
                    }
                    const mapForRole = new Map<string, AccessControlLevel>()
                    for (const [resourceKey, control] of Object.entries(entry.accessControlByResource)) {
                        if (control?.access_level !== null && control?.access_level !== undefined) {
                            mapForRole.set(resourceKey, control.access_level as AccessControlLevel)
                        }
                    }
                    out.set(entry.role.id, mapForRole)
                }
                return out
            },
        ],

        resourceMemberOverrideByMemberIdAndResourceKey: [
            (s) => [s.memberResourceAccessControls],
            (memberResourceAccessControls): Map<string, Map<string, AccessControlLevel>> => {
                const out = new Map<string, Map<string, AccessControlLevel>>()
                for (const entry of memberResourceAccessControls) {
                    if (!entry.organization_member) {
                        continue
                    }
                    const mapForMember = new Map<string, AccessControlLevel>()
                    for (const [resourceKey, control] of Object.entries(entry.accessControlByResource)) {
                        if (control?.access_level !== null && control?.access_level !== undefined) {
                            mapForMember.set(resourceKey, control.access_level as AccessControlLevel)
                        }
                    }
                    out.set(entry.organization_member.id, mapForMember)
                }
                return out
            },
        ],

        allRows: [
            (s) => [
                s.canUseRoles,
                s.defaultResourceAccessControls,
                s.allMembers,
                s.projectDefaultLevel,
                s.projectMemberOverrideByMemberId,
                s.projectResourceLabel,
                s.projectRoleOverrideByRoleId,
                s.resourceMemberOverrideByMemberIdAndResourceKey,
                s.resourceRoleOverrideByRoleIdAndResourceKey,
                s.resources,
                s.roles,
            ],
            (
                canUseRoles,
                defaultResourceAccessControls,
                allMembers,
                projectDefaultLevel,
                projectMemberOverrideByMemberId,
                projectResourceLabel,
                projectRoleOverrideByRoleId,
                resourceMemberOverrideByMemberIdAndResourceKey,
                resourceRoleOverrideByRoleIdAndResourceKey,
                resources,
                roles
            ): AccessControlRow[] => {
                const resourcesList = resources as unknown as AccessControlType['resource'][]
                const rows: AccessControlRow[] = []

                const addRow = (row: Omit<AccessControlRow, 'id'>): void => {
                    rows.push({
                        ...row,
                        id: `${row.scopeType}:${row.scopeId ?? 'default'}:${row.resourceKey}`,
                    })
                }

                // Default scope rows
                addRow({
                    scopeType: 'default',
                    scopeId: null,
                    scopeLabel: 'Default',
                    resourceKey: 'project',
                    resourceLabel: projectResourceLabel,
                    level: projectDefaultLevel,
                    isException: true,
                })

                for (const resourceKey of resourcesList) {
                    const explicitLevel = defaultResourceAccessControls.accessControlByResource[resourceKey]
                        ?.access_level as AccessControlLevel | null | undefined
                    if (explicitLevel === null || explicitLevel === undefined) {
                        continue
                    }
                    addRow({
                        scopeType: 'default',
                        scopeId: null,
                        scopeLabel: 'Default',
                        resourceKey,
                        resourceLabel: toSentenceCase(pluralizeResource(resourceKey as APIScopeObject)),
                        level: explicitLevel,
                        isException: true,
                    })
                }

                // Role scope rows
                if (canUseRoles) {
                    for (const role of roles ?? []) {
                        const roleProjectOverride = projectRoleOverrideByRoleId.get(role.id)
                        if (roleProjectOverride !== undefined) {
                            addRow({
                                scopeType: 'role',
                                scopeId: role.id,
                                scopeLabel: role.name,
                                resourceKey: 'project',
                                resourceLabel: projectResourceLabel,
                                level: roleProjectOverride,
                                isException: true,
                            })
                        }

                        const overrides = resourceRoleOverrideByRoleIdAndResourceKey.get(role.id)
                        if (overrides) {
                            for (const [resourceKey, level] of overrides.entries()) {
                                addRow({
                                    scopeType: 'role',
                                    scopeId: role.id,
                                    scopeLabel: role.name,
                                    resourceKey: resourceKey as APIScopeObject,
                                    resourceLabel: toSentenceCase(pluralizeResource(resourceKey as APIScopeObject)),
                                    level: level,
                                    isException: true,
                                })
                            }
                        }
                    }
                }

                // Member scope rows
                for (const member of allMembers) {
                    const memberProjectOverride = projectMemberOverrideByMemberId.get(member.id)
                    if (memberProjectOverride !== undefined) {
                        addRow({
                            scopeType: 'member',
                            scopeId: member.id,
                            scopeLabel: fullName(member.user),
                            resourceKey: 'project',
                            resourceLabel: projectResourceLabel,
                            level: memberProjectOverride,
                            isException: true,
                        })
                    }

                    const overrides = resourceMemberOverrideByMemberIdAndResourceKey.get(member.id)
                    if (overrides) {
                        for (const [resourceKey, level] of overrides.entries()) {
                            addRow({
                                scopeType: 'member',
                                scopeId: member.id,
                                scopeLabel: fullName(member.user),
                                resourceKey: resourceKey as APIScopeObject,
                                resourceLabel: toSentenceCase(pluralizeResource(resourceKey as APIScopeObject)),
                                level: level,
                                isException: true,
                            })
                        }
                    }
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
                    .map((level) => ({ key: level, label: humanizeAccessControlLevel(level as AccessControlLevel) }))
            },
        ],

        scopedRows: [
            (s) => [s.activeTab, s.allRows, s.canUseRoles, s.filters],
            (activeTab, allRows, canUseRoles, filters: AccessControlFilters): AccessControlRow[] => {
                const scopeType: ScopeType = scopeTypeForAccessControlsTab(activeTab as AccessControlsTab)
                let rows = allRows.filter((row) => row.scopeType === scopeType)

                if (scopeType === 'role') {
                    if (!canUseRoles) {
                        return []
                    }
                    if (filters.roleIds.length > 0) {
                        rows = rows.filter((row) => (row.scopeId ? filters.roleIds.includes(row.scopeId) : false))
                    }
                }

                if (scopeType === 'member') {
                    if (filters.memberIds.length > 0) {
                        rows = rows.filter((row) => (row.scopeId ? filters.memberIds.includes(row.scopeId) : false))
                    }
                }

                return rows
            },
        ],

        filteredSortedRows: [
            (s) => [s.scopedRows, s.searchText, s.filters],
            (scopedRows, searchText, filters: AccessControlFilters): AccessControlRow[] => {
                const search = searchText.trim().toLowerCase()

                const filtered = scopedRows.filter((row) => {
                    if (filters.resourceKeys.length > 0 && !filters.resourceKeys.includes(row.resourceKey)) {
                        return false
                    }

                    if (filters.ruleLevels.length > 0) {
                        if (row.level !== null && !filters.ruleLevels.includes(row.level)) {
                            return false
                        }
                    }

                    if (search.length > 0) {
                        const levelText = humanizeAccessControlLevel(row.level)
                        const haystack = `${row.scopeLabel} ${row.resourceLabel} ${levelText}`.toLowerCase()

                        if (!haystack.includes(search)) {
                            return false
                        }
                    }

                    return true
                })

                return [...filtered].sort(sortAccessControlRows)
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
    }),

    listeners(({ actions }) => ({
        deleteRule: async ({ row }) => {
            const isProjectRule = row.resourceKey === 'project'

            if (isProjectRule) {
                if (row.scopeType === 'role' && row.scopeId) {
                    actions.updateAccessControlRoles([{ role: row.scopeId, level: null }])
                } else if (row.scopeType === 'member' && row.scopeId) {
                    actions.updateAccessControlMembers([{ member: row.scopeId, level: null }])
                }

                return
            }

            actions.updateResourceAccessControls(
                [
                    {
                        resource: row.resourceKey as APIScopeObject,
                        access_level: null,
                        role: row.scopeType === 'role' ? row.scopeId : null,
                        organization_member: row.scopeType === 'member' ? row.scopeId : null,
                    },
                ],
                row.scopeType
            )
        },

        saveRule: async ({ scopeType, scopeId, resourceKey, level }) => {
            const isProjectRule = resourceKey === 'project'

            if (isProjectRule) {
                if (scopeType === 'default') {
                    actions.updateAccessControlDefault(level)
                    actions.closeRuleModal()
                    return
                }
                if (scopeType === 'role' && scopeId) {
                    actions.updateAccessControlRoles([{ role: scopeId, level }])
                    actions.closeRuleModal()
                    return
                }
                if (scopeType === 'member' && scopeId) {
                    actions.updateAccessControlMembers([{ member: scopeId, level }])
                    actions.closeRuleModal()
                    return
                }
                return
            }

            actions.updateResourceAccessControls(
                [
                    {
                        resource: resourceKey as APIScopeObject,
                        access_level: level,
                        role: scopeType === 'role' ? scopeId : null,
                        organization_member: scopeType === 'member' ? scopeId : null,
                    },
                ],
                scopeType
            )
            actions.closeRuleModal()
        },
    })),
])
