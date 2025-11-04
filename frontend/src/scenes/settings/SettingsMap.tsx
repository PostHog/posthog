import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { ExceptionAutocaptureSettings } from '@posthog/products-error-tracking/frontend/scenes/ErrorTrackingConfigurationScene/ExceptionAutocaptureSettings'
import { ErrorTrackingAlerting } from '@posthog/products-error-tracking/frontend/scenes/ErrorTrackingConfigurationScene/alerting/ErrorTrackingAlerting'
import { AutoAssignmentRules } from '@posthog/products-error-tracking/frontend/scenes/ErrorTrackingConfigurationScene/rules/AutoAssignmentRules'
import { CustomGroupingRules } from '@posthog/products-error-tracking/frontend/scenes/ErrorTrackingConfigurationScene/rules/CustomGroupingRules'
import { SymbolSets } from '@posthog/products-error-tracking/frontend/scenes/ErrorTrackingConfigurationScene/symbol_sets/SymbolSets'
import { EventConfiguration } from '@posthog/products-revenue-analytics/frontend/settings/EventConfiguration'
import { ExternalDataSourceConfiguration } from '@posthog/products-revenue-analytics/frontend/settings/ExternalDataSourceConfiguration'
import { FilterTestAccountsConfiguration as RevenueAnalyticsFilterTestAccountsConfiguration } from '@posthog/products-revenue-analytics/frontend/settings/FilterTestAccountsConfiguration'
import { GoalsConfiguration } from '@posthog/products-revenue-analytics/frontend/settings/GoalsConfiguration'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { organizationLogic } from 'scenes/organizationLogic'
import { BounceRateDurationSetting } from 'scenes/settings/environment/BounceRateDuration'
import { BounceRatePageViewModeSetting } from 'scenes/settings/environment/BounceRatePageViewMode'
import { CookielessServerHashModeSetting } from 'scenes/settings/environment/CookielessServerHashMode'
import { CustomChannelTypes } from 'scenes/settings/environment/CustomChannelTypes'
import { DeadClicksAutocaptureSettings } from 'scenes/settings/environment/DeadClicksAutocaptureSettings'
import { MaxMemorySettings } from 'scenes/settings/environment/MaxMemorySettings'
import { PersonsJoinMode } from 'scenes/settings/environment/PersonsJoinMode'
import { PersonsOnEvents } from 'scenes/settings/environment/PersonsOnEvents'
import { PreAggregatedTablesSetting } from 'scenes/settings/environment/PreAggregatedTablesSetting'
import { ReplayTriggers } from 'scenes/settings/environment/ReplayTriggers'
import { SessionsTableVersion } from 'scenes/settings/environment/SessionsTableVersion'
import { SessionsV2JoinModeSettings } from 'scenes/settings/environment/SessionsV2JoinModeSettings'
import { urls } from 'scenes/urls'

import { RolesAccessControls } from '~/layout/navigation-3000/sidepanel/panels/access_control/RolesAccessControls'
import { AccessControlLevel, AccessControlResourceType, Realm } from '~/types'

import { IntegrationsList } from '../../lib/integrations/IntegrationsList'
import {
    ActivityLogNotifications,
    ActivityLogOrgLevelSettings,
    ActivityLogSettings,
} from './environment/ActivityLogSettings'
import { AutocaptureSettings, WebVitalsAutocaptureSettings } from './environment/AutocaptureSettings'
import { CSPReportingSettings } from './environment/CSPReportingSettings'
import { CorrelationConfig } from './environment/CorrelationConfig'
import { DataAttributes } from './environment/DataAttributes'
import { DataColorThemes } from './environment/DataColorThemes'
import { ErrorTrackingIntegrations } from './environment/ErrorTrackingIntegrations'
import { FeatureFlagSettings } from './environment/FeatureFlagSettings'
import { FeaturePreviewsSettings } from './environment/FeaturePreviewsSettings'
import { GroupAnalyticsConfig } from './environment/GroupAnalyticsConfig'
import { HeatmapsSettings } from './environment/HeatmapsSettings'
import { HumanFriendlyComparisonPeriodsSetting } from './environment/HumanFriendlyComparisonPeriodsSetting'
import { IPAllowListInfo } from './environment/IPAllowListInfo'
import { IPCapture } from './environment/IPCapture'
import { GithubIntegration } from './environment/Integrations'
import MCPServerSettings from './environment/MCPServerSettings'
import { ManagedReverseProxy } from './environment/ManagedReverseProxy'
import { MarketingAnalyticsSettingsWrapper } from './environment/MarketingAnalyticsSettingsWrapper'
import { PathCleaningFiltersConfig } from './environment/PathCleaningFiltersConfig'
import { PersonDisplayNameProperties } from './environment/PersonDisplayNameProperties'
import {
    NetworkCaptureSettings,
    ReplayAISettings,
    ReplayAuthorizedDomains,
    ReplayDataRetentionSettings,
    ReplayGeneral,
    ReplayMaskingSettings,
} from './environment/SessionRecordingSettings'
import { SlackIntegration } from './environment/SlackIntegration'
import { SurveySettings } from './environment/SurveySettings'
import { TeamAccessControl } from './environment/TeamAccessControl'
import { TeamDangerZone } from './environment/TeamDangerZone'
import {
    Bookmarklet,
    TeamAuthorizedURLs,
    TeamDisplayName,
    TeamTimezone,
    TeamVariables,
    WebSnippet,
} from './environment/TeamSettings'
import { ProjectAccountFiltersSetting } from './environment/TestAccountFiltersConfig'
import { UsageMetricsConfig } from './environment/UsageMetricsConfig'
import { WebAnalyticsEnablePreAggregatedTables } from './environment/WebAnalyticsAPISetting'
import { WebhookIntegration } from './environment/WebhookIntegration'
import { Invites } from './organization/Invites'
import { Members } from './organization/Members'
import { OrganizationAI } from './organization/OrgAI'
import { OrganizationDisplayName } from './organization/OrgDisplayName'
import { OrganizationEmailPreferences } from './organization/OrgEmailPreferences'
import { OrganizationExperimentStatsMethod } from './organization/OrgExperimentStatsMethod'
import { OrganizationLogo } from './organization/OrgLogo'
import { OrganizationDangerZone } from './organization/OrganizationDangerZone'
import { OrganizationSecuritySettings } from './organization/OrganizationSecuritySettings'
import { VerifiedDomains } from './organization/VerifiedDomains/VerifiedDomains'
import { ProjectDangerZone } from './project/ProjectDangerZone'
import { ProjectMove } from './project/ProjectMove'
import { ProjectDisplayName } from './project/ProjectSettings'
import { SettingSection } from './types'
import { ChangePassword } from './user/ChangePassword'
import { HedgehogModeSettings } from './user/HedgehogModeSettings'
import { OptOutCapture } from './user/OptOutCapture'
import { PersonalAPIKeys } from './user/PersonalAPIKeys'
import { ThemeSwitcher } from './user/ThemeSwitcher'
import { TwoFactorSettings } from './user/TwoFactorSettings'
import { UpdateEmailPreferences } from './user/UpdateEmailPreferences'
import { UserDangerZone } from './user/UserDangerZone'
import { UserDetails } from './user/UserDetails'

export const SETTINGS_MAP: SettingSection[] = [
    // ENVIRONMENT
    {
        level: 'environment',
        id: 'environment-details',
        title: 'General',
        settings: [
            {
                id: 'display-name',
                title: 'Display name',
                component: <TeamDisplayName />,
            },
            {
                id: 'snippet',
                title: 'Web snippet',
                component: <WebSnippet />,
            },
            {
                id: 'authorized-urls',
                title: 'Toolbar Authorized URLs',
                component: <TeamAuthorizedURLs />,
            },
            {
                id: 'bookmarklet',
                title: 'Bookmarklet',
                component: <Bookmarklet />,
            },
            {
                id: 'variables',
                title: 'Project ID',
                component: <TeamVariables />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-autocapture',
        title: 'Autocapture & heatmaps',

        settings: [
            {
                id: 'autocapture',
                title: 'Autocapture',
                component: <AutocaptureSettings />,
            },
            {
                id: 'autocapture-data-attributes',
                title: 'Data attributes',
                component: <DataAttributes />,
            },
            {
                id: 'heatmaps',
                title: 'Heatmaps',
                component: <HeatmapsSettings />,
            },
            {
                id: 'web-vitals-autocapture',
                title: 'Web vitals autocapture',
                component: <WebVitalsAutocaptureSettings />,
            },
            {
                id: 'dead-clicks-autocapture',
                title: 'Dead clicks autocapture',
                component: <DeadClicksAutocaptureSettings />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-customer-analytics',
        title: 'Customer analytics',
        flag: 'CUSTOMER_ANALYTICS',
        settings: [
            {
                id: 'group-analytics',
                title: 'Group analytics',
                component: <GroupAnalyticsConfig />,
            },
            {
                id: 'crm-usage-metrics',
                title: 'Usage metrics',
                component: <UsageMetricsConfig />,
                flag: 'CRM_USAGE_METRICS',
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-product-analytics',
        title: 'Product analytics',
        settings: [
            {
                id: 'date-and-time',
                title: 'Date & time',
                component: <TeamTimezone />,
            },
            {
                id: 'base-currency',
                title: 'Base currency',
                component: <BaseCurrency hideTitle />,
            },
            {
                id: 'internal-user-filtering',
                title: 'Filter out internal and test users',
                component: <ProjectAccountFiltersSetting />,
            },
            {
                id: 'data-theme',
                title: (
                    <>
                        Chart color themes
                        <LemonTag type="warning" className="ml-1 uppercase">
                            Beta
                        </LemonTag>
                    </>
                ),
                component: <DataColorThemes />,
            },
            {
                id: 'persons-on-events',
                title: 'Person properties mode',
                component: <PersonsOnEvents />,
                flag: '!SETTINGS_PERSONS_ON_EVENTS_HIDDEN', // Setting hidden for Cloud orgs created since June 2024
            },
            {
                id: 'correlation-analysis',
                title: 'Correlation analysis exclusions',
                component: <CorrelationConfig />,
            },
            {
                id: 'person-display-name',
                title: 'Person display name',
                component: <PersonDisplayNameProperties />,
            },
            {
                id: 'path-cleaning',
                title: 'Path cleaning rules',
                component: <PathCleaningFiltersConfig />,
            },
            {
                id: 'datacapture',
                title: 'IP data capture configuration',
                component: <IPCapture />,
            },
            {
                id: 'human-friendly-comparison-periods',
                title: 'Human friendly comparison periods',
                component: <HumanFriendlyComparisonPeriodsSetting />,
            },
            {
                id: 'group-analytics',
                title: 'Group analytics',
                component: <GroupAnalyticsConfig />,
                flag: '!CUSTOMER_ANALYTICS',
            },
            {
                id: 'persons-join-mode',
                title: 'Persons join mode',
                component: <PersonsJoinMode />,
                flag: 'SETTINGS_PERSONS_JOIN_MODE',
            },
            {
                id: 'session-table-version',
                title: 'Sessions Table Version',
                component: <SessionsTableVersion />,
                flag: 'SETTINGS_SESSION_TABLE_VERSION',
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-revenue-analytics',
        title: 'Revenue analytics',
        accessControl: {
            resourceType: AccessControlResourceType.RevenueAnalytics,
            minimumAccessLevel: AccessControlLevel.Editor,
        },
        settings: [
            {
                id: 'revenue-base-currency',
                title: 'Base currency',
                component: (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.RevenueAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <BaseCurrency hideTitle />
                    </AccessControlAction>
                ),
                hideWhenNoSection: true,
            },
            {
                id: 'revenue-analytics-filter-test-accounts',
                title: 'Filter test accounts out of revenue analytics',
                component: <RevenueAnalyticsFilterTestAccountsConfiguration />,
            },
            {
                id: 'revenue-analytics-goals',
                title: 'Revenue goals',
                component: <GoalsConfiguration />,
            },
            {
                id: 'revenue-analytics-events',
                title: 'Revenue events',
                component: <EventConfiguration />,
            },
            {
                id: 'revenue-analytics-external-data-sources',
                title: 'External data sources',
                component: <ExternalDataSourceConfiguration />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-marketing-analytics',
        title: 'Marketing analytics',
        flag: 'WEB_ANALYTICS_MARKETING',
        settings: [
            {
                id: 'marketing-settings',
                title: 'Marketing settings',
                component: <MarketingAnalyticsSettingsWrapper />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-web-analytics',
        title: 'Web analytics',
        settings: [
            {
                id: 'web-analytics-authorized-urls',
                title: 'Web Analytics Domains',
                component: <TeamAuthorizedURLs />,
            },
            {
                id: 'channel-type',
                title: 'Custom channel type',
                component: <CustomChannelTypes />,
            },
            {
                id: 'cookieless-server-hash-mode',
                title: 'Cookieless server hash mode',
                component: <CookielessServerHashModeSetting />,
            },
            {
                id: 'bounce-rate-duration',
                title: 'Bounce rate duration',
                component: <BounceRateDurationSetting />,
            },
            {
                id: 'bounce-rate-page-view-mode',
                title: 'Bounce rate page view mode',
                component: <BounceRatePageViewModeSetting />,
                flag: 'SETTINGS_BOUNCE_RATE_PAGE_VIEW_MODE',
            },
            {
                id: 'session-join-mode',
                title: 'Session join mode',
                component: <SessionsV2JoinModeSettings />,
                flag: 'SETTINGS_SESSIONS_V2_JOIN',
            },
            {
                id: 'web-analytics-pre-aggregated-tables',
                title: 'Pre-aggregated tables',
                component: <PreAggregatedTablesSetting />,
                flag: 'SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES',
            },
            {
                id: 'web-analytics-opt-in-pre-aggregated-tables-and-api',
                title: 'New query engine',
                component: <WebAnalyticsEnablePreAggregatedTables />,
                flag: 'WEB_ANALYTICS_API',
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-replay',
        title: 'Session replay',
        settings: [
            {
                id: 'replay',
                title: 'Session replay',
                component: <ReplayGeneral />,
            },
            {
                id: 'replay-triggers',
                title: 'Recording conditions',
                component: <ReplayTriggers />,
            },
            {
                id: 'replay-masking',
                title: 'Privacy and masking',
                component: <ReplayMaskingSettings />,
            },
            {
                id: 'replay-network',
                title: 'Network capture',
                component: <NetworkCaptureSettings />,
            },
            {
                id: 'replay-authorized-domains',
                title: 'Authorized domains for replay',
                component: <ReplayAuthorizedDomains />,
                allowForTeam: (t) => !!t?.recording_domains?.length,
            },
            {
                id: 'replay-ai-config',
                title: 'AI recording summary',
                component: <ReplayAISettings />,
                flag: 'AI_SESSION_PERMISSIONS',
            },
            {
                id: 'replay-retention',
                title: (
                    <>
                        Data retention
                        <LemonTag type="success" className="ml-1 uppercase">
                            New
                        </LemonTag>
                    </>
                ),
                component: <ReplayDataRetentionSettings />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-surveys',
        title: 'Surveys',
        settings: [
            {
                id: 'surveys-interface',
                title: 'Surveys web interface',
                component: <SurveySettings />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-feature-flags',
        title: 'Feature flags',
        settings: [
            {
                id: 'feature-flags-interface',
                title: 'Feature flags',
                component: <FeatureFlagSettings />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-error-tracking',
        title: 'Error tracking',
        settings: [
            {
                id: 'error-tracking-exception-autocapture',
                title: 'Exception autocapture',
                component: <ExceptionAutocaptureSettings />,
            },
            {
                id: 'error-tracking-alerting',
                title: 'Alerting',
                component: <ErrorTrackingAlerting />,
            },
            {
                id: 'error-tracking-auto-assignment',
                title: 'Auto assignment rules',
                component: <AutoAssignmentRules />,
            },
            {
                id: 'error-tracking-custom-grouping',
                title: 'Custom grouping rules',
                component: <CustomGroupingRules />,
            },
            {
                id: 'error-tracking-integrations',
                title: 'Integrations',
                component: <ErrorTrackingIntegrations />,
            },
            {
                id: 'error-tracking-symbol-sets',
                title: 'Symbol sets',
                component: <SymbolSets />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-csp-reporting',
        title: 'CSP reporting',
        flag: 'CSP_REPORTING',
        settings: [
            {
                id: 'csp-reporting',
                title: (
                    <>
                        CSP reporting{' '}
                        <LemonTag type="warning" className="ml-1 uppercase">
                            Beta
                        </LemonTag>
                    </>
                ),
                component: <CSPReportingSettings />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-max',
        title: 'AI',
        flag: 'ARTIFICIAL_HOG',
        settings: [
            {
                id: 'core-memory',
                title: 'Memory',
                description:
                    "PostHog AI automatically remembers details about your company and product. This context helps our AI assistant provide relevant answers and suggestions. If there are any details you don't want PostHog AI to remember, you can edit or remove them below.",
                component: <MaxMemorySettings />,
                hideOn: [Realm.SelfHostedClickHouse, Realm.SelfHostedPostgres],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-integrations',
        title: 'Integrations',
        settings: [
            {
                id: 'integration-webhooks',
                title: 'Webhook integration',
                component: <WebhookIntegration />,
            },
            {
                id: 'integration-slack',
                title: 'Slack integration',
                component: <SlackIntegration />,
            },
            {
                id: 'integration-github',
                title: 'GitHub integration',
                component: <GithubIntegration />,
            },
            {
                id: 'integration-other',
                title: 'Other integrations',
                component: <IntegrationsList omitKinds={['slack', 'github']} />,
            },
            {
                id: 'integration-ip-allowlist',
                title: 'Static IP addresses',
                component: <IPAllowListInfo />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-access-control',
        title: 'Access control',
        settings: [
            {
                id: 'environment-access-control',
                title: 'Access control',
                component: <TeamAccessControl />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-activity-logs',
        title: 'Activity logs',
        settings: [
            {
                id: 'activity-log-settings',
                title: 'Logs',
                component: <ActivityLogSettings />,
            },
            {
                id: 'activity-log-org-level-settings',
                title: 'Settings',
                component: <ActivityLogOrgLevelSettings />,
                flag: 'CDP_ACTIVITY_LOG_NOTIFICATIONS',
            },
            {
                id: 'activity-log-notifications',
                title: 'Notifications',
                component: <ActivityLogNotifications />,
                flag: 'CDP_ACTIVITY_LOG_NOTIFICATIONS',
            },
        ],
    },
    {
        level: 'environment',
        id: 'mcp-server',
        // hideSelfHost: true,
        title: 'MCP Server',
        settings: [
            {
                id: 'mcp-server-configure',
                title: 'Model Context Protocol (MCP) server',
                component: <MCPServerSettings />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-danger-zone',
        title: 'Danger zone',
        settings: [
            {
                id: 'project-move',
                title: 'Move project',
                flag: '!ENVIRONMENTS',
                component: <ProjectMove />, // There isn't EnvironmentMove yet
                allowForTeam: () =>
                    (organizationLogic.findMounted()?.values.currentOrganization?.teams.length ?? 0) > 1,
            },
            {
                id: 'environment-delete',
                title: 'Delete environment',
                component: <TeamDangerZone />,
            },
        ],
    },

    // PROJECT - just project-details and project-danger-zone
    {
        level: 'project',
        id: 'project-details',
        title: 'General',
        settings: [
            {
                id: 'display-name',
                title: 'Display name',
                component: <ProjectDisplayName />,
            },
        ],
    },
    {
        level: 'project',
        id: 'project-danger-zone',
        title: 'Danger zone',
        settings: [
            {
                id: 'project-move',
                title: 'Move project',
                component: <ProjectMove />,
                allowForTeam: () =>
                    (organizationLogic.findMounted()?.values.currentOrganization?.teams.length ?? 0) > 1,
            },
            {
                id: 'project-delete',
                title: 'Delete project',
                component: <ProjectDangerZone />,
            },
        ],
    },

    // ORGANIZATION
    {
        level: 'organization',
        id: 'organization-details',
        title: 'General',
        settings: [
            {
                id: 'organization-display-name',
                title: 'Display name',
                component: <OrganizationDisplayName />,
            },
            {
                id: 'organization-logo',
                title: 'Logo',
                component: <OrganizationLogo />,
            },
            {
                id: 'organization-ai-consent',
                title: 'PostHog AI data analysis',
                description: (
                    // Note: Sync the copy below with AIConsentPopoverWrapper.tsx
                    <>
                        PostHog AI features, such as our assistant Max, use{' '}
                        <Tooltip title={`As of ${dayjs().format('MMMM YYYY')}: OpenAI`}>
                            <dfn>external AI services</dfn>
                        </Tooltip>{' '}
                        for data analysis.
                        <br />
                        This <i>can</i> involve transfer of identifying user data, so we ask for your org-wide consent
                        below.
                        <br />
                        <strong>Your data will not be used for training models.</strong>
                    </>
                ),
                component: <OrganizationAI />,
            },
            {
                id: 'organization-experiment-stats-method',
                title: 'Default experiment statistical method',
                description:
                    'Choose which statistical method to use by default for new experiments in this organization. Individual experiments can override this setting.',
                component: <OrganizationExperimentStatsMethod />,
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-members',
        title: 'Members',
        settings: [
            {
                id: 'invites',
                title: 'Pending invites',
                component: <Invites />,
            },
            {
                id: 'members',
                title: 'Organization members',
                component: <Members />,
            },
            {
                id: 'email-members',
                title: 'Notification preferences',
                component: <OrganizationEmailPreferences />,
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-roles',
        title: 'Roles',
        settings: [
            {
                id: 'organization-roles',
                title: 'Roles',
                component: <RolesAccessControls />,
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-authentication',
        title: 'Authentication domains & SSO',
        settings: [
            {
                id: 'authentication-domains',
                title: 'Authentication Domains',
                component: <VerifiedDomains />,
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-proxy',
        title: 'Managed reverse proxy',
        settings: [
            {
                id: 'organization-proxy',
                title: 'Managed reverse proxies',
                component: <ManagedReverseProxy />,
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-security',
        title: 'Security settings',
        settings: [
            {
                id: 'organization-security',
                title: 'Security settings',
                component: <OrganizationSecuritySettings />,
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-danger-zone',
        title: 'Danger zone',
        settings: [
            {
                id: 'organization-delete',
                title: 'Delete organization',
                component: <OrganizationDangerZone />,
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-billing',
        hideSelfHost: true,
        title: 'Billing',
        to: urls.organizationBilling(),
        settings: [],
    },
    {
        level: 'organization',
        id: 'organization-startup-program',
        hideSelfHost: true,
        title: 'Startup program',
        to: urls.startups(),
        settings: [],
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        flag: 'STARTUP_PROGRAM_INTENT',
    },

    // USER
    {
        level: 'user',
        id: 'user-profile',
        title: 'Profile',
        settings: [
            {
                id: 'details',
                title: 'Details',
                component: <UserDetails />,
            },
            {
                id: 'change-password',
                title: 'Change password',
                component: <ChangePassword />,
            },
            {
                id: '2fa',
                title: 'Two-factor authentication',
                component: <TwoFactorSettings />,
            },
        ],
    },
    {
        level: 'user',
        id: 'user-api-keys',
        title: 'Personal API keys',
        settings: [
            {
                id: 'personal-api-keys',
                title: 'Personal API keys',
                component: <PersonalAPIKeys />,
            },
        ],
    },
    {
        level: 'user',
        id: 'user-feature-previews',
        title: 'Feature previews',
        settings: [
            {
                id: 'feature-previews',
                title: 'Feature previews',
                component: <FeaturePreviewsSettings />,
            },
        ],
    },
    {
        level: 'user',
        id: 'user-notifications',
        title: 'Notifications',
        settings: [
            {
                id: 'notifications',
                title: 'Notifications',
                component: <UpdateEmailPreferences />,
            },
        ],
    },
    {
        level: 'user',
        id: 'user-customization',
        title: 'Customization',
        settings: [
            {
                id: 'theme',
                title: 'Theme',
                component: <ThemeSwitcher onlyLabel />,
            },
            {
                id: 'optout',
                title: 'Anonymize data collection',
                component: <OptOutCapture />,
                hideOn: [Realm.Cloud],
            },
            {
                id: 'hedgehog-mode',
                title: 'Hedgehog mode',
                component: <HedgehogModeSettings />,
            },
            {
                id: 'customization-irl',
                title: 'Customization IRL',
                component: (
                    <div>
                        Grab some{' '}
                        <Link to="https://posthog.com/merch" target="_blank">
                            PostHog merch
                        </Link>{' '}
                        to customize yourself outside of the app
                    </div>
                ),
            },
        ],
    },
    {
        level: 'user',
        id: 'user-danger-zone',
        title: 'Danger zone',
        settings: [
            {
                id: 'user-delete',
                title: 'Delete account',
                component: <UserDangerZone />,
            },
        ],
    },
]
