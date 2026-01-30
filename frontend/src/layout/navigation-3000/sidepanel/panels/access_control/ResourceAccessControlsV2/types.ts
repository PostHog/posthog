import { APIScopeObject, OrganizationMemberType, RoleType } from '~/types'

import { AccessControlLevelMapping } from './accessControlsLogic'

export type ScopeType = 'default' | 'role' | 'member'

export type AccessControlRow = {
    id: string
    levels: AccessControlLevelMapping[]
    member?: OrganizationMemberType
    role: Pick<RoleType, 'id' | 'name'>
}

export type RuleModalState = {
    row: AccessControlRow
}

export type AccessControlsTab = 'defaults' | 'roles' | 'members'

export type AccessControlFilters = {
    roleIds: string[]
    memberIds: string[]
    resourceKeys: APIScopeObject[]
    ruleLevels: string[]
}
