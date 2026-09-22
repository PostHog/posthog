import {
    APIScopeObject,
    AccessControlLevel,
    AccessControlMembersResponse,
    AccessControlRolesResponse,
    EffectiveAccessControlEntry,
} from '~/types'

export type ScopeType = 'default' | 'role' | 'member'

/** Why a subject falls back to the level they do, as the settings UI phrases it. Derived from the
 * entry's inherited_access provenance by inheritedReasonOf(). */
export type InheritedReason = 'project_default' | 'role_override' | 'organization_admin' | null

export type AccessControlRoleEntry = AccessControlRolesResponse['results'][number]
export type AccessControlMemberEntry = AccessControlMembersResponse['results'][number]

export type AccessControlSettingsEntry = AccessControlRoleEntry | AccessControlMemberEntry

export type GroupedAccessControlRuleModalLogicProps = {
    entry: AccessControlSettingsEntry
    scopeType: ScopeType
    projectId: string
}

export type AccessControlsTab = 'defaults' | 'roles' | 'members'

export type AccessControlFilters = {
    roleIds: string[]
    memberIds: string[]
    resourceKeys: APIScopeObject[]
    ruleLevels: AccessControlLevel[]
}

export type FormAccessLevel = AccessControlLevel | null // null means "no override"

export type EntryData = {
    project: Pick<EffectiveAccessControlEntry, 'access_level' | 'effective_access_level' | 'inherited_access'>
    resources: Record<
        string,
        Pick<EffectiveAccessControlEntry, 'access_level' | 'effective_access_level' | 'inherited_access'>
    >
}
