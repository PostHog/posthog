import { EitherMembershipLevel, FEATURE_FLAGS } from 'lib/constants'

import { Realm, TeamPublicType, TeamType } from '~/types'

export type SettingsLogicProps = {
    logicKey?: string
    // Optional - if given, renders only the given level
    settingLevelId?: SettingLevelId
    // Optional - if given, renders only the given section
    sectionId?: SettingSectionId
    // Optional - if given, renders only the given setting
    settingId?: SettingId
}

export const SettingLevelIds = ['environment', 'project', 'organization', 'user'] as const
export type SettingLevelId = (typeof SettingLevelIds)[number]

export type SettingSectionId =
    | 'environment-details'
    | 'environment-autocapture'
    | 'environment-product-analytics'
    | 'environment-web-analytics'
    | 'environment-replay'
    | 'environment-surveys'
    | 'environment-toolbar'
    | 'environment-integrations'
    | 'environment-access-control'
    | 'environment-role-based-access-control'
    | 'environment-danger-zone'
    | 'project-details'
    | 'project-autocapture' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-product-analytics' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-replay' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-surveys' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-toolbar' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-integrations' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-access-control' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-role-based-access-control' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-danger-zone'
    | 'organization-details'
    | 'organization-members'
    | 'organization-authentication'
    | 'organization-roles'
    | 'organization-proxy'
    | 'organization-danger-zone'
    | 'user-profile'
    | 'user-api-keys'
    | 'user-customization'

export type SettingId =
    | 'replay-triggers'
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
    | 'replay-network'
    | 'replay-authorized-domains'
    | 'replay-ingestion'
    | 'surveys-interface'
    | 'authorized-toolbar-urls'
    | 'integration-webhooks'
    | 'integration-slack'
    | 'integration-other'
    | 'integration-ip-allowlist'
    | 'environment-access-control'
    | 'environment-role-based-access-control'
    | 'environment-delete'
    | 'project-delete'
    | 'organization-logo'
    | 'organization-display-name'
    | 'invites'
    | 'members'
    | 'email-members'
    | 'authentication-domains'
    | 'organization-roles'
    | 'organization-delete'
    | 'organization-proxy'
    | 'product-description'
    | 'details'
    | 'change-password'
    | '2fa'
    | 'personal-api-keys'
    | 'notifications'
    | 'optout'
    | 'theme'
    | 'replay-ai-config'
    | 'heatmaps'
    | 'hedgehog-mode'
    | 'persons-join-mode'
    | 'bounce-rate-page-view-mode'
    | 'session-table-version'
    | 'web-vitals-autocapture'
    | 'dead-clicks-autocapture'
    | 'channel-type'

type FeatureFlagKey = keyof typeof FEATURE_FLAGS

export type Setting = {
    id: SettingId
    title: string
    description?: JSX.Element | string
    component: JSX.Element
    /**
     * Feature flag to gate the setting being shown.
     * If prefixed with !, the condition is inverted - the setting will only be shown if the is flag false.
     * When an array is provided, the setting will be shown if ALL of the conditions are met.
     */
    flag?: FeatureFlagKey | `!${FeatureFlagKey}` | (FeatureFlagKey | `!${FeatureFlagKey}`)[]
    hideOn?: Realm[]
    /**
     * defaults to true if not provided
     * can check if a team should have access to a setting and return false if not
     */
    allowForTeam?: (team: TeamType | TeamPublicType | null) => boolean
}

export interface SettingSection extends Pick<Setting, 'flag'> {
    id: SettingSectionId
    title: string
    level: SettingLevelId
    settings: Setting[]
    minimumAccessLevel?: EitherMembershipLevel
}
