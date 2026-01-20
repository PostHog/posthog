import { APIScopeObject, AccessControlLevel } from '~/types'

export type ScopeType = 'default' | 'role' | 'member'

export type AccessControlRow = {
    id: string
    scopeType: ScopeType
    scopeId: string | null
    scopeLabel: string
    resourceKey: APIScopeObject
    resourceLabel: string
    level: AccessControlLevel | null
    isException: boolean
}

export type RuleModalState =
    | {
          mode: 'add'
          initialScopeType?: ScopeType
      }
    | {
          mode: 'edit'
          row: AccessControlRow
      }

export type AccessControlsTab = 'defaults' | 'roles' | 'members'

export type AccessControlFilters = {
    roleIds: string[]
    memberIds: string[]
    resourceKeys: APIScopeObject[]
    ruleLevels: string[]
}
