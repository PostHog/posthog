import type { OrganizationBasicType, TeamBasicType } from '~/types'

export type OrganizationOption = Pick<OrganizationBasicType, 'id' | 'name'>
export type TeamOption = Pick<TeamBasicType, 'id' | 'name' | 'organization' | 'api_token'>

export type AccessType = 'all' | 'organizations' | 'teams'
export type RequiredAccessLevel = 'organization' | 'team' | null

export type ScopeAccessSelectorProps = {
    organizations: OrganizationOption[]
    /** Undefined while the projects are still loading, so the picker can show a spinner. */
    teams?: TeamOption[]
    accessType?: AccessType
    requiredAccessLevel?: RequiredAccessLevel
    autoSelectFirst?: boolean
    teamsLoadFailed?: boolean
    onReloadTeams?: () => void
}

export type SelectorMode = 'single' | 'multiple'

export type OrganizationSelectorProps = {
    organizations: OrganizationOption[]
    mode: SelectorMode
    value?: string[]
    onChange?: (val: string[]) => void
}

export type TeamSelectorProps = {
    /** Undefined while the projects are still loading, so the picker can show a spinner. */
    teams?: TeamOption[]
    organizations: OrganizationOption[]
    mode: SelectorMode
    value?: string[]
    onChange?: (val: string[]) => void
    loadFailed?: boolean
    onReload?: () => void
}
