import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
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
    EntryData,
    GroupedAccessControlRuleModalLogicProps,
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
        const allKeys = ['project', ...Object.keys(entry.resources)] as APIScopeObject[]
        const hasMatchingLevel = filters.ruleLevels.some((rl) =>
            allKeys.some((k) => getEffectiveLevel(entry, k) === rl)
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
            resourcesAccessControlLogic,
            ['resources'],
        ],
    })),

    actions({
        setActiveTab: (activeTab: AccessControlsTab) => ({ activeTab }),
        setFilters: (filters: Partial<AccessControlFilters>) => ({ filters }),
        setSearchText: (searchText: string) => ({ searchText }),
        openRuleModal: (state: GroupedAccessControlRuleModalLogicProps) => ({ state }),
        closeRuleModal: true,
        saveGroupedRules: (params: {
            scopeType: ScopeType
            scopeId: string
            projectLevel: AccessControlLevel | null
            resourceLevels: Record<APIScopeObject, AccessControlLevel | null>
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
            null as GroupedAccessControlRuleModalLogicProps | null,
            {
                openRuleModal: (
                    _: GroupedAccessControlRuleModalLogicProps | null,
                    { state }: { state: GroupedAccessControlRuleModalLogicProps }
                ) => state,
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
            (s) => [s.defaults, s.resources],
            (defaults, resources): { key: APIScopeObject; label: string }[] => {
                if (defaults) {
                    return Object.keys(defaults.resource_access_levels).map((resource) => ({
                        key: resource as APIScopeObject,
                        label: toSentenceCase(pluralizeResource(resource as APIScopeObject)),
                    }))
                }
                // Fallback to list of all resources while loading
                return resources.map((resource) => ({
                    key: resource,
                    label: toSentenceCase(pluralizeResource(resource)),
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
            (projectLevels, resourceLevels): { key: AccessControlLevel; label: string }[] => {
                const levelSet = new Set<AccessControlLevel>()
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

    listeners(({ actions, values }) => ({
        setActiveTab: ({ activeTab }) => {
            // Lazy load data for the tab
            if (activeTab === 'roles' && !values.rolesData && !values.rolesDataLoading) {
                actions.loadRoles()
            } else if (activeTab === 'members' && !values.membersData && !values.membersDataLoading) {
                actions.loadMembers()
            }
        },

        saveGroupedRules: async ({ scopeType, scopeId, projectLevel, resourceLevels }) => {
            // If the selected level equals the inherited level, we save null (clear override)
            // If the selected level differs from inherited, we save it as an override

            let entryData: EntryData | null = null

            if (scopeType === 'default' && values.defaults) {
                // For defaults, there's no inheritance
                entryData = {
                    project: {
                        access_level: values.defaults.project_access_level,
                        effective_access_level: values.defaults.project_access_level,
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

            const updates: { resource: APIScopeObject; level: AccessControlLevel | null }[] = []

            // Process project
            const currentProjectEffective = entryData.project.effective_access_level
            const currentProjectSaved = entryData.project.access_level
            const projectInherited = entryData.project.inherited_access_level

            if (projectLevel !== currentProjectEffective) {
                // User changed the level - determine what to save
                // If new level equals inherited, save null (clear override)
                // Otherwise save the new level
                const levelToSave = projectLevel === projectInherited ? null : projectLevel
                if (levelToSave !== currentProjectSaved) {
                    updates.push({ resource: 'project' as APIScopeObject, level: levelToSave })
                }
            }

            // Process resources
            const allResourceKeys = new Set<APIScopeObject>([
                ...(Object.keys(entryData.resources) as APIScopeObject[]),
                ...(Object.keys(resourceLevels) as APIScopeObject[]),
            ])

            for (const resourceKey of allResourceKeys) {
                const resourceEntry = entryData.resources[resourceKey]
                const newLevel = resourceLevels[resourceKey] ?? null
                const currentEffective = resourceEntry?.effective_access_level ?? null
                const currentSaved = resourceEntry?.access_level ?? null
                const inherited = resourceEntry?.inherited_access_level ?? null

                if (newLevel !== currentEffective) {
                    // If new level equals inherited (or both null), save null (clear override)
                    // Otherwise save the new level
                    const levelToSave = newLevel === inherited ? null : newLevel
                    if (levelToSave !== currentSaved) {
                        updates.push({ resource: resourceKey, level: levelToSave })
                    }
                }
            }

            const projectUpdate = updates.find((u) => u.resource === 'project')
            const otherUpdates = updates.filter((u) => u.resource !== 'project')

            if (projectUpdate) {
                if (scopeType === 'default') {
                    actions.updateAccessControlDefault(projectUpdate.level ?? AccessControlLevel.None)
                } else if (scopeType === 'role') {
                    actions.updateAccessControlRoles([{ role: scopeId, level: projectUpdate.level }])
                } else if (scopeType === 'member') {
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
            // Only reload roles/members if they were already loaded
            if (values.rolesData) {
                actions.loadRoles()
            }
            if (values.membersData) {
                actions.loadMembers()
            }
        },
        updateAccessControlRolesSuccess: () => {
            actions.loadRoles()
            // Members inherit from roles, so reload if already loaded
            if (values.membersData) {
                actions.loadMembers()
            }
        },
        updateAccessControlMembersSuccess: () => {
            actions.loadMembers()
        },
        updateResourceAccessControlsSuccess: () => {
            actions.loadDefaults()
            // Only reload roles/members if they were already loaded
            if (values.rolesData) {
                actions.loadRoles()
            }
            if (values.membersData) {
                actions.loadMembers()
            }
        },
    })),

    afterMount(({ actions }) => {
        // Only load defaults, roles/members are lazy loaded when their tab is opened
        actions.loadDefaults()
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
