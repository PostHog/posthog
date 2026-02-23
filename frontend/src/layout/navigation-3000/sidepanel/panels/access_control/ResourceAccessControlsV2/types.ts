import { APIScopeObject, AccessControlLevel, AccessControlMembersResponse, AccessControlRolesResponse } from '~/types'

export type ScopeType = 'default' | 'role' | 'member'

export type InheritedReason = 'project_default' | 'role_override' | 'organization_admin' | null | undefined

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
    ruleLevels: string[]
}

export type FormAccessLevel = AccessControlLevel | null // null means "no override"
