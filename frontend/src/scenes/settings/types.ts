import { EitherMembershipLevel, FEATURE_FLAGS } from 'lib/constants'

import { AvailableFeature } from '~/types'

export type SettingsLogicProps = {
    logicKey?: string
    // Optional - if given, renders only the given level
    settingLevelId?: SettingLevelId
    // Optional - if given, renders only the given section
    sectionId?: SettingSectionId
    // Optional - if given, renders only the given setting
    settingId?: SettingId
}

export type SettingLevelId = 'user' | 'project' | 'organization'
export const SettingLevelIds: SettingLevelId[] = ['project', 'organization', 'user']

export type SettingSectionId =
    | 'project-details'
    | 'project-autocapture'
    | 'project-product-analytics'
    | 'project-replay'
    | 'project-surveys'
    | 'project-toolbar'
    | 'project-integrations'
    | 'project-rbac'
    | 'project-danger-zone'
    | 'organization-details'
    | 'organization-members'
    | 'organization-authentication'
    | 'organization-rbac'
    | 'organization-danger-zone'
    | 'user-profile'
    | 'user-api-keys'
    | 'user-customization'

export type SettingId =
    | 'display-name'
    | 'snippet'
    | 'bookmarklet'
    | 'variables'
    | 'autocapture'
    | 'exception-autocapture'
    | 'autocapture-data-attributes'
    | 'date-and-time'
    | 'internal-user-filtering'
    | 'correlation-analysis'
    | 'person-display-name'
    | 'path-cleaning'
    | 'datacapture'
    | 'group-analytics'
    | 'persons-on-events'
    | 'replay'
    | 'replay-authorized-domains'
    | 'replay-ingestion'
    | 'surveys-interface'
    | 'authorized-toolbar-urls'
    | 'integration-webhooks'
    | 'integration-slack'
    | 'project-rbac'
    | 'project-delete'
    | 'organization-display-name'
    | 'invites'
    | 'members'
    | 'email-members'
    | 'authentication-domains'
    | 'organization-rbac'
    | 'organization-delete'
    | 'details'
    | 'change-password'
    | '2fa'
    | 'personal-api-keys'
    | 'notifications'
    | 'optout'
    | 'theme'

export type Setting = {
    id: SettingId
    title: string
    description?: JSX.Element | string
    component: JSX.Element
    flag?: keyof typeof FEATURE_FLAGS
    features?: AvailableFeature[]
}

export type SettingSection = {
    id: SettingSectionId
    title: string
    level: SettingLevelId
    settings: Setting[]
    flag?: keyof typeof FEATURE_FLAGS
    minimumAccessLevel?: EitherMembershipLevel
}
