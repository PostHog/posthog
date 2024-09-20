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
    | 'project-access-control'
    | 'project-role-based-access-control'
    | 'project-danger-zone'
    | 'organization-details'
    | 'organization-members'
    | 'organization-authentication'
    | 'organization-rbac'
    | 'organization-proxy'
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
    | 'replay-network'
    | 'replay-authorized-domains'
    | 'replay-ingestion'
    | 'surveys-interface'
    | 'authorized-toolbar-urls'
    | 'integration-webhooks'
    | 'integration-slack'
    | 'integration-other'
    | 'integration-ip-allowlist'
    | 'project-access-control'
    | 'project-role-based-access-control'
    | 'project-delete'
    | 'organization-logo'
    | 'organization-display-name'
    | 'invites'
    | 'members'
    | 'email-members'
    | 'authentication-domains'
    | 'organization-rbac'
    | 'organization-delete'
    | 'organization-proxy'
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

type FeatureFlagKey = keyof typeof FEATURE_FLAGS

export type Setting = {
    id: SettingId
    title: string
    description?: JSX.Element | string
    component: JSX.Element
    /**
     * Feature flag to gate the setting being shown.
     * If prefixed with !, the condition is inverted - the setting will only be shown if the is flag false.
     */
    flag?: FeatureFlagKey | `!${FeatureFlagKey}`
    features?: AvailableFeature[]
}

export type SettingSection = {
    id: SettingSectionId
    title: string
    level: SettingLevelId
    settings: Setting[]
    /**
     * Feature flag to gate the section being shown.
     * If prefixed with !, the condition is inverted - the section will only be shown if the is flag false.
     */
    flag?: FeatureFlagKey | `!${FeatureFlagKey}`
    minimumAccessLevel?: EitherMembershipLevel
}
