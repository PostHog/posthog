import { APIScopeObject, AccessControlMembersResponse, AccessControlRolesResponse } from '~/types'

export type ScopeType = 'default' | 'role' | 'member'

export type AccessControlRoleEntry = AccessControlRolesResponse['results'][number]
export type AccessControlMemberEntry = AccessControlMembersResponse['results'][number]

export type AccessControlSettingsEntry = AccessControlRoleEntry | AccessControlMemberEntry

export type RuleModalState = {
    scopeType: ScopeType
    entry: AccessControlSettingsEntry
}

export type AccessControlsTab = 'defaults' | 'roles' | 'members'

export type AccessControlFilters = {
    roleIds: string[]
    memberIds: string[]
    resourceKeys: APIScopeObject[]
    ruleLevels: string[]
}
