import { EitherMembershipLevel, FEATURE_FLAGS } from 'lib/constants'

import { AccessControlLevel, AccessControlResourceType, Realm, TeamPublicType, TeamType } from '~/types'

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
    | 'environment-customer-analytics'
    | 'environment-product-analytics'
    | 'environment-revenue-analytics'
    | 'environment-marketing-analytics'
    | 'environment-web-analytics'
    | 'environment-replay'
    | 'environment-surveys'
    | 'environment-feature-flags'
    | 'environment-error-tracking'
    | 'environment-csp-reporting'
    | 'environment-max'
    | 'environment-integrations'
    | 'environment-activity-logs'
    | 'environment-access-control'
    | 'environment-danger-zone'
    | 'project-details'
    | 'project-danger-zone'
    | 'project-autocapture' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-product-analytics' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-replay' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-surveys' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-integrations' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'project-access-control' // TODO: This section is for backward compat – remove when Environments are rolled out
    | 'organization-details'
    | 'organization-members'
    | 'organization-roles'
    | 'organization-authentication'
    | 'organization-proxy'
    | 'organization-security'
    | 'organization-danger-zone'
    | 'organization-billing'
    | 'organization-startup-program'
    | 'user-profile'
    | 'user-api-keys'
    | 'user-notifications'
    | 'user-customization'
    | 'user-danger-zone'
    | 'user-feature-previews'
    | 'mcp-server'

export type SettingId =
    | 'replay-triggers'
    | 'display-name'
    | 'snippet'
    | 'authorized-urls'
    | 'web-analytics-authorized-urls'
    | 'bookmarklet'
    | 'variables'
    | 'autocapture'
    | 'autocapture-data-attributes'
    | 'date-and-time'
    | 'internal-user-filtering'
    | 'data-theme'
    | 'correlation-analysis'
    | 'crm-usage-metrics'
    | 'person-display-name'
    | 'path-cleaning'
    | 'datacapture'
    | 'human-friendly-comparison-periods'
    | 'group-analytics'
    | 'persons-on-events'
    | 'replay'
    | 'replay-network'
    | 'replay-masking'
    | 'replay-authorized-domains'
    | 'replay-ingestion'
    | 'replay-retention'
    | 'surveys-interface'
    | 'feature-flags-interface'
    | 'error-tracking-exception-autocapture'
    | 'error-tracking-custom-grouping'
    | 'error-tracking-user-groups'
    | 'error-tracking-symbol-sets'
    | 'error-tracking-alerting'
    | 'error-tracking-integrations'
    | 'error-tracking-auto-assignment'
    | 'integration-webhooks'
    | 'integration-slack'
    | 'integration-error-tracking'
    | 'integration-github'
    | 'integration-other'
    | 'integration-ip-allowlist'
    | 'environment-access-control'
    | 'environment-delete'
    | 'project-delete'
    | 'project-move'
    | 'organization-logo'
    | 'organization-display-name'
    | 'invites'
    | 'members'
    | 'email-members'
    | 'authentication-domains'
    | 'organization-ai-consent'
    | 'organization-experiment-stats-method'
    | 'organization-roles'
    | 'organization-delete'
    | 'organization-proxy'
    | 'organization-security'
    | 'details'
    | 'change-password'
    | '2fa'
    | 'personal-api-keys'
    | 'notifications'
    | 'feature-previews'
    | 'optout'
    | 'theme'
    | 'replay-ai-config'
    | 'heatmaps'
    | 'hedgehog-mode'
    | 'persons-join-mode'
    | 'bounce-rate-page-view-mode'
    | 'session-join-mode'
    | 'bounce-rate-duration'
    | 'revenue-base-currency'
    | 'revenue-analytics-filter-test-accounts'
    | 'revenue-analytics-goals'
    | 'revenue-analytics-events'
    | 'revenue-analytics-external-data-sources'
    | 'session-table-version'
    | 'web-vitals-autocapture'
    | 'dead-clicks-autocapture'
    | 'channel-type'
    | 'cookieless-server-hash-mode'
    | 'user-groups'
    | 'user-delete'
    | 'web-revenue-events'
    | 'core-memory'
    | 'customization-irl'
    | 'web-analytics-pre-aggregated-tables'
    | 'web-analytics-opt-in-pre-aggregated-tables-and-api'
    | 'csp-reporting'
    | 'base-currency'
    | 'marketing-settings'
    | 'mcp-server-configure'
    | 'organization-ip-anonymization-default'

type FeatureFlagKey = keyof typeof FEATURE_FLAGS

export type Setting = {
    id: SettingId
    title: JSX.Element | string
    description?: JSX.Element | string
    component: JSX.Element
    searchTerm?: string
    hideOn?: Realm[]

    /**
     * Feature flag to gate the setting being shown.
     * If prefixed with !, the condition is inverted - the setting will only be shown if the is flag false.
     * When an array is provided, the setting will be shown if ALL of the conditions are met.
     */
    flag?: FeatureFlagKey | `!${FeatureFlagKey}` | (FeatureFlagKey | `!${FeatureFlagKey}`)[]

    /**
     * defaults to true if not provided
     * can check if a team should have access to a setting and return false if not
     */
    allowForTeam?: (team: TeamType | TeamPublicType | null) => boolean

    /**
     * If true, this setting will be hidden when viewing all settings (no specific section selected),
     * but will still appear when viewing its specific section directly
     */
    hideWhenNoSection?: boolean
}

export interface SettingSection extends Pick<Setting, 'flag'> {
    id: SettingSectionId
    to?: string
    title: JSX.Element | string
    hideSelfHost?: boolean
    level: SettingLevelId
    settings: Setting[]
    minimumAccessLevel?: EitherMembershipLevel
    searchValue?: string

    /**
     * If the setting is restricted, the resource type and minimum access level
     * that are required to access the setting
     */
    accessControl?: {
        resourceType: AccessControlResourceType
        minimumAccessLevel: AccessControlLevel
    }
}
