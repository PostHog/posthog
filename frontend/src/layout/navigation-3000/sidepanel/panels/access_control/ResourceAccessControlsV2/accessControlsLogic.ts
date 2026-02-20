import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { toSentenceCase } from 'lib/utils'
import { pluralizeResource } from 'lib/utils/accessControlUtils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import {
    APIScopeObject,
    AccessControlDefaultsResponse,
    AccessControlLevel,
    AccessControlMembersResponse,
    AccessControlRolesResponse,
    AvailableFeature,
    OrganizationMemberType,
} from '~/types'

import { accessControlLogic } from '../accessControlLogic'
import { resourcesAccessControlLogic } from '../resourcesAccessControlLogic'
import { roleAccessControlLogic } from '../roleAccessControlLogic'
import type { accessControlsLogicType } from './accessControlsLogicType'
import {
    AccessControlFilters,
    AccessControlMemberEntry,
    AccessControlRoleEntry,
    AccessControlSettingsEntry,
    AccessControlsTab,
    RuleModalState,
    ScopeType,
} from './types'

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
    level: AccessControlLevel | null
}

export type GroupedAccessControlRulesForm = {
    scopeId: string | null
    levels: AccessControlLevelMapping[]
}

export function getEntryId(entry: AccessControlSettingsEntry): string {
    if ('role_id' in entry) {
        return entry.role_id
    }
    return entry.organization_membership_id
}

export function getEntryName(entry: AccessControlSettingsEntry): string {
    if ('role_name' in entry) {
        return entry.role_name
    }
    return entry.user.first_name || entry.user.email
}

function getEffectiveLevel(entry: AccessControlSettingsEntry, resourceKey: APIScopeObject): AccessControlLevel | null {
    if (resourceKey === 'project') {
        return entry.project.effective_access_level ?? null
    }
    return entry.resources[resourceKey]?.effective_access_level ?? null
}

function matchesFilters(entry: AccessControlSettingsEntry, filters: AccessControlFilters): boolean {
    if (filters.resourceKeys.length > 0) {
        const hasEffectiveAccessToFilteredResource = filters.resourceKeys.some(
            (rk) => getEffectiveLevel(entry, rk) !== null
        )
        if (!hasEffectiveAccessToFilteredResource) {
            return false
        }
    }

    if (filters.ruleLevels.length > 0) {
        const hasMatchingLevel = filters.ruleLevels.some(
            (rl) =>
                getEffectiveLevel(entry, 'project' as APIScopeObject) === rl ||
                Object.keys(entry.resources).some((r) => getEffectiveLevel(entry, r as APIScopeObject) === rl)
        )
        if (!hasMatchingLevel) {
            return false
        }
    }

    return true
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
        actions: [
            resourcesAccessControlLogic,
            ['updateResourceAccessControls', 'updateResourceAccessControlsSuccess'],
            accessControlLogic({
                resource: 'project',
                resource_id: props.projectId,
                title: '',
                description: '',
            }),
            [
                'updateAccessControlDefault',
                'updateAccessControlDefaultSuccess',
                'updateAccessControlMembers',
                'updateAccessControlMembersSuccess',
                'updateAccessControlRoles',
                'updateAccessControlRolesSuccess',
            ],
        ],
        values: [
            userLogic,
            ['hasAvailableFeature'],
            membersLogic,
            ['sortedMembers'],
            roleAccessControlLogic,
            ['roles'],
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

    loaders(() => ({
        defaults: [
            null as AccessControlDefaultsResponse | null,
            {
                loadDefaults: async () =>
                    api.get<AccessControlDefaultsResponse>('api/projects/@current/access_control_defaults'),
            },
        ],
        rolesData: [
            null as AccessControlRolesResponse | null,
            {
                loadRoles: async () =>
                    api.get<AccessControlRolesResponse>('api/projects/@current/access_control_roles'),
            },
        ],
        membersData: [
            null as AccessControlMembersResponse | null,
            {
                loadMembers: async () =>
                    api.get<AccessControlMembersResponse>('api/projects/@current/access_control_members'),
            },
        ],
    })),

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
        allMembers: [(s) => [s.sortedMembers], (sortedMembers): OrganizationMemberType[] => sortedMembers ?? []],

        canUseRoles: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS),
        ],

        canEdit: [(s) => [s.defaults], (defaults): boolean => defaults?.can_edit ?? false],

        availableProjectLevels: [
            (s) => [s.defaults],
            (defaults): AccessControlLevel[] => defaults?.available_project_levels ?? [],
        ],

        availableResourceLevels: [
            (s) => [s.defaults],
            (defaults): AccessControlLevel[] => defaults?.available_resource_levels ?? [],
        ],

        resourceKeys: [
            (s) => [s.defaults],
            (defaults): { key: APIScopeObject; label: string }[] => {
                if (!defaults) {
                    return []
                }
                return Object.keys(defaults.resource_access_levels).map((resource) => ({
                    key: resource as APIScopeObject,
                    label: toSentenceCase(pluralizeResource(resource as APIScopeObject)),
                }))
            },
        ],

        resourcesWithProject: [
            (s) => [s.resourceKeys],
            (resourceKeys): { key: APIScopeObject; label: string }[] => {
                return [{ key: 'project' as APIScopeObject, label: 'Project' }, ...resourceKeys]
            },
        ],

        ruleOptions: [
            (s) => [s.availableProjectLevels, s.availableResourceLevels],
            (projectLevels, resourceLevels): { key: string; label: string }[] => {
                const levelSet = new Set<string>()
                for (const level of projectLevels) {
                    levelSet.add(level)
                }
                for (const level of resourceLevels) {
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

        filteredRoles: [
            (s) => [s.rolesData, s.searchText, s.filters, s.canUseRoles],
            (rolesData, searchText, filters, canUseRoles): AccessControlRoleEntry[] => {
                if (!canUseRoles || !rolesData) {
                    return []
                }
                const search = searchText.trim().toLowerCase()
                return rolesData.results.filter((role) => {
                    if (filters.roleIds.length > 0 && !filters.roleIds.includes(role.role_id)) {
                        return false
                    }
                    if (search.length > 0 && !role.role_name.toLowerCase().includes(search)) {
                        return false
                    }
                    return matchesFilters(role, filters)
                })
            },
        ],

        filteredMembers: [
            (s) => [s.membersData, s.searchText, s.filters],
            (membersData, searchText, filters): AccessControlMemberEntry[] => {
                if (!membersData) {
                    return []
                }
                const search = searchText.trim().toLowerCase()
                return membersData.results.filter((member) => {
                    if (
                        filters.memberIds.length > 0 &&
                        !filters.memberIds.includes(member.organization_membership_id)
                    ) {
                        return false
                    }
                    const name = (member.user.first_name || member.user.email).toLowerCase()
                    if (
                        search.length > 0 &&
                        !name.includes(search) &&
                        !member.user.email.toLowerCase().includes(search)
                    ) {
                        return false
                    }
                    return matchesFilters(member, filters)
                })
            },
        ],

        loading: [
            (s) => [s.defaultsLoading, s.rolesDataLoading, s.membersDataLoading],
            (defaultsLoading, rolesLoading, membersLoading): boolean =>
                defaultsLoading || rolesLoading || membersLoading,
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
            // If the selected level equals the inherited level, we save null (clear override)
            // If the selected level differs from inherited, we save it as an override

            type AccessLevelState = {
                access_level: AccessControlLevel | null
                effective_access_level: AccessControlLevel | null
                inherited_access_level: AccessControlLevel | null
            }
            type EntryData = {
                project: AccessLevelState
                resources: Record<string, AccessLevelState>
            }

            let entryData: EntryData | null = null

            if (scopeType === 'default' && values.defaults) {
                // For defaults, there's no inheritance
                const projectLevel = values.defaults.project_access_level
                entryData = {
                    project: {
                        access_level: projectLevel,
                        effective_access_level: projectLevel,
                        inherited_access_level: null,
                    },
                    resources: Object.fromEntries(
                        Object.entries(values.defaults.resource_access_levels).map(([k, v]) => [
                            k,
                            {
                                access_level: v.access_level,
                                effective_access_level: v.access_level,
                                inherited_access_level: null,
                            },
                        ])
                    ),
                }
            } else if (scopeType === 'role') {
                const role = values.rolesData?.results.find((r) => r.role_id === scopeId)
                if (role) {
                    entryData = { project: role.project, resources: role.resources }
                }
            } else if (scopeType === 'member') {
                const member = values.membersData?.results.find((m) => m.organization_membership_id === scopeId)
                if (member) {
                    entryData = { project: member.project, resources: member.resources }
                }
            }

            if (!entryData) {
                actions.closeRuleModal()
                return
            }

            const newLevelsMap = new Map(levels.map((l) => [l.resourceKey, l.level]))
            const updates: { resource: APIScopeObject; level: AccessControlLevel | null }[] = []

            // Process project
            const newProjectLevel = newLevelsMap.get('project' as APIScopeObject) ?? null
            const currentProjectEffective = entryData.project.effective_access_level
            const currentProjectSaved = entryData.project.access_level
            const projectInherited = entryData.project.inherited_access_level

            if (newProjectLevel !== currentProjectEffective) {
                // User changed the level - determine what to save
                // If new level equals inherited, save null (clear override)
                // Otherwise save the new level
                const levelToSave = newProjectLevel === projectInherited ? null : newProjectLevel
                if (levelToSave !== currentProjectSaved) {
                    updates.push({ resource: 'project' as APIScopeObject, level: levelToSave })
                }
            }

            // Process resources
            const allResourceKeys = new Set<APIScopeObject>([
                ...(Object.keys(entryData.resources) as APIScopeObject[]),
                ...levels.filter((l) => l.resourceKey !== 'project').map((l) => l.resourceKey),
            ])

            for (const resourceKey of allResourceKeys) {
                const resourceEntry = entryData.resources[resourceKey]
                const newLevel = newLevelsMap.get(resourceKey) ?? null
                const currentEffective = resourceEntry?.effective_access_level ?? null
                const currentSaved = resourceEntry?.access_level ?? null
                const inherited = resourceEntry?.inherited_access_level ?? null

                if (newLevel !== currentEffective) {
                    // If new level equals inherited (or both null), save null (clear override)
                    // Otherwise save the new level
                    const levelToSave = newLevel === inherited ? null : newLevel
                    if (levelToSave !== currentSaved) {
                        updates.push({ resource: resourceKey as APIScopeObject, level: levelToSave })
                    }
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

        updateAccessControlDefaultSuccess: () => {
            actions.loadDefaults()
            actions.loadRoles()
            actions.loadMembers()
        },
        updateAccessControlRolesSuccess: () => {
            actions.loadRoles()
            actions.loadMembers()
        },
        updateAccessControlMembersSuccess: () => {
            actions.loadMembers()
        },
        updateResourceAccessControlsSuccess: () => {
            actions.loadDefaults()
            actions.loadRoles()
            actions.loadMembers()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadDefaults()
        actions.loadRoles()
        actions.loadMembers()
    }),

    urlToAction(({ actions }) => ({
        '/settings/:section': (_, searchParams) => {
            const tab = searchParams.access_tab
            if (tab === 'roles' || tab === 'members' || tab === 'defaults') {
                actions.setActiveTab(tab)
            }
            if (tab === 'roles' && searchParams.access_role_id) {
                actions.setFilters({ roleIds: [searchParams.access_role_id] })
            }
        },
    })),
])
