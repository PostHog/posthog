import { PlatformSupportConfig } from 'lib/components/SupportedPlatforms/types'
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
    // Environment
    | 'environment-details'
    | 'environment-access-control'
    | 'environment-activity-logs'
    | 'environment-ai-observability'
    | 'environment-approvals'
    | 'environment-autocapture'
    | 'environment-conversations'
    | 'environment-csp-reporting'
    | 'environment-customer-analytics'
    | 'environment-customization'
    | 'environment-discussions'
    | 'environment-error-tracking'
    | 'environment-error-tracking-configuration'
    | 'environment-experiments'
    | 'environment-exports'
    | 'environment-feature-flags'
    | 'environment-heatmaps'
    | 'environment-integrations'
    | 'environment-logs'
    | 'environment-marketing-analytics'
    | 'environment-max'
    | 'environment-privacy'
    | 'environment-product-analytics'
    | 'environment-replay'
    | 'environment-revenue-analytics'
    | 'environment-secret-api-keys'
    | 'environment-surveys'
    | 'environment-web-analytics'
    | 'environment-workflows'
    | 'environment-danger-zone'
    // Project (backward compat – remove when Environments are rolled out)
    | 'project-details'
    | 'project-access-control'
    | 'project-ai-observability'
    | 'project-autocapture'
    | 'project-integrations'
    | 'project-product-analytics'
    | 'project-replay'
    | 'project-surveys'
    | 'project-danger-zone'
    // Organization
    | 'organization-details'
    | 'organization-authentication'
    | 'organization-billing'
    | 'organization-cimd-verification-tokens'
    | 'organization-integrations'
    | 'organization-legal-documents'
    | 'organization-members'
    | 'organization-oauth-apps'
    | 'organization-proxy'
    | 'organization-roles'
    | 'organization-security'
    | 'organization-startup-program'
    | 'organization-danger-zone'
    // User
    | 'user-profile'
    | 'user-api-keys'
    | 'user-connected-apps'
    | 'user-customization'
    | 'user-feature-previews'
    | 'user-notifications'
    | 'user-personal-integrations'
    | 'user-reminders'
    | 'user-danger-zone'
    // Standalone
    | 'mcp-servers'
    | 'posthog-mcp'

export type SettingId =
    | '2fa'
    | 'activity-log-notifications'
    | 'activity-log-org-level-settings'
    | 'activity-log-settings'
    | 'ai-observability-byok'
    | 'ai-observability-parser-recipes'
    | 'allow-impersonation'
    | 'approval-policies'
    | 'authentication-domains'
    | 'autocapture'
    | 'autocapture-data-attributes'
    | 'banner'
    | 'base-currency'
    | 'bounce-rate-duration'
    | 'bounce-rate-page-view-mode'
    | 'business-model'
    | 'change-password'
    | 'change-requests'
    | 'changelog'
    | 'channel-type'
    | 'connected-apps'
    | 'conversations-ai'
    | 'conversations-channels'
    | 'conversations-general'
    | 'conversations-imports'
    | 'conversations-notifications'
    | 'cookieless-server-hash-mode'
    | 'core-memory'
    | 'correlation-analysis'
    | 'csp-reporting'
    | 'customer-analytics-accounts'
    | 'customer-analytics-dashboard-events'
    | 'customer-analytics-usage-metrics'
    | 'customization-irl'
    | 'data-theme'
    | 'datacapture'
    | 'date-and-time'
    | 'dead-clicks-autocapture'
    | 'details'
    | 'discussion-mention-integrations'
    | 'display-name'
    | 'environment-access-control'
    | 'environment-delete'
    | 'environment-experiment-confidence-level'
    | 'environment-experiment-cuped-enabled'
    | 'environment-experiment-cuped-lookback-days'
    | 'environment-experiment-matured-users'
    | 'environment-experiment-mde'
    | 'environment-experiment-recalculation-time'
    | 'environment-experiment-sequential-testing-enabled'
    | 'environment-experiment-sequential-tuning-parameter'
    | 'environment-experiment-stats-method'
    | 'environment-secret-api-keys'
    | 'error-tracking-alerting'
    | 'error-tracking-auto-assignment'
    | 'error-tracking-custom-grouping'
    | 'error-tracking-exception-autocapture'
    | 'error-tracking-ingestion-controls'
    | 'error-tracking-integrations'
    | 'error-tracking-rate-limits'
    | 'error-tracking-releases'
    | 'error-tracking-spike-detection'
    | 'error-tracking-suppression-rules'
    | 'error-tracking-symbol-sets'
    | 'error-tracking-user-groups'
    | 'feature-flag-confirmation'
    | 'feature-flag-default-evaluation-contexts'
    | 'feature-flag-default-release-conditions'
    | 'feature-flag-evaluation-context-suggestions'
    | 'feature-flag-require-evaluation-contexts'
    | 'feature-flag-secure-api-key'
    | 'feature-flags-interface'
    | 'feature-previews'
    | 'feature-previews-coming-soon'
    | 'group-analytics'
    | 'heatmaps'
    | 'hedgehog-mode'
    | 'human-friendly-comparison-periods'
    | 'integration-error-tracking'
    | 'integration-github'
    | 'integration-ip-allowlist'
    | 'integration-linear'
    | 'integration-other'
    | 'integration-slack'
    | 'integration-webhooks'
    | 'internal-user-filtering'
    | 'invites'
    | 'logs'
    | 'logs-alerting'
    | 'logs-distinct-id-attribute-key'
    | 'logs-drop-rules'
    | 'logs-json-parse'
    | 'logs-pii-scrub'
    | 'logs-retention'
    | 'marketing-settings'
    | 'mcp-hints'
    | 'mcp-servers-manage'
    | 'members'
    | 'notifications'
    | 'optout'
    | 'organization-admin-notice'
    | 'organization-ai-consent'
    | 'organization-ai-training-opt-out'
    | 'organization-cimd-verification-tokens-list'
    | 'organization-default-role'
    | 'organization-delete'
    | 'organization-display-name'
    | 'organization-experiment-stats-method'
    | 'organization-integrations-list'
    | 'organization-ip-anonymization-default'
    | 'organization-oauth-apps-list'
    | 'organization-proxy'
    | 'organization-roles'
    | 'organization-security'
    | 'organization-personal-api-keys'
    | 'passkeys'
    | 'login-sessions'
    | 'path-cleaning'
    | 'person-display-name'
    | 'person-last-seen-at'
    | 'personal-api-keys'
    | 'personal-integrations-github'
    | 'personal-integrations-slack'
    | 'persons-join-mode'
    | 'reminders'
    | 'persons-on-events'
    | 'posthog-mcp-configure'
    | 'project-delete'
    | 'project-move'
    | 'realtime-notifications'
    | 'replay'
    | 'replay-ai-config'
    | 'replay-authorized-domains'
    | 'replay-canvas-capture'
    | 'replay-ingestion'
    | 'replay-integrations'
    | 'replay-log-capture'
    | 'replay-masking'
    | 'replay-network'
    | 'replay-network-headers-payloads'
    | 'replay-retention'
    | 'replay-triggers'
    | 'revenue-analytics-events'
    | 'revenue-analytics-external-data-sources'
    | 'revenue-analytics-filter-test-accounts'
    | 'revenue-analytics-goals'
    | 'revenue-base-currency'
    | 'session-table-version'
    | 'sidebar-auto-suggest'
    | 'snippet'
    | 'snippet-v2'
    | 'surveys-default-appearance'
    | 'surveys-interface'
    | 'theme'
    | 'user-delete'
    | 'user-groups'
    | 'variables'
    | 'web-analytics-achievements'
    | 'web-analytics-authorized-urls'
    | 'web-analytics-opt-in-pre-aggregated-tables-and-api'
    | 'web-analytics-pre-aggregated-tables'
    | 'web-revenue-events'
    | 'web-vitals-autocapture'
    | 'workflows-engagement-events'

type FeatureFlagKey = keyof typeof FEATURE_FLAGS

export type Setting = {
    id: SettingId
    title: JSX.Element | string | null
    description?: JSX.Element | string
    component: JSX.Element
    searchTerm?: string
    hideOn?: Realm[]

    /**
     * Feature flag to gate the setting being shown.
     * If prefixed with !, the condition is inverted - the setting will only be shown if the is flag false.
     * When an array is provided, the setting will be shown if ALL of the conditions are met.
     * When a tuple is provided, the setting will be shown if the feature flag is enabled and the value matches the given value.
     */
    flag?:
        | FeatureFlagKey
        | `!${FeatureFlagKey}`
        | (FeatureFlagKey | `!${FeatureFlagKey}`)[]
        | [[FeatureFlagKey, string | boolean]]

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

    /** Additional search terms that help users find this setting (e.g. ['ip', 'anonymize', 'gdpr']) */
    keywords?: string[]

    /** Plaintext description for search indexing when `description` is JSX */
    searchDescription?: string

    /** URL to relevant PostHog documentation */
    docsUrl?: string

    /** Platform/SDK availability rendered as badges to the right of the title */
    platformSupport?: PlatformSupportConfig
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

    /**
     * Optional group name to organize sections under collapsible headers.
     * Sections with the same group will be nested under a group header.
     */
    group?: string

    /**
     * When true, the section is hidden from the settings page navigation and search
     * but remains accessible when referenced directly via sectionId (e.g. from a
     * product's own configuration scene).
     */
    hideFromNavigation?: boolean
}
