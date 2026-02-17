import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { ErrorTrackingAlerting } from '@posthog/products-error-tracking/frontend/scenes/ErrorTrackingConfigurationScene/alerting/ErrorTrackingAlerting'
import { Releases } from '@posthog/products-error-tracking/frontend/scenes/ErrorTrackingConfigurationScene/releases/Releases'
import { AutoAssignmentRules } from '@posthog/products-error-tracking/frontend/scenes/ErrorTrackingConfigurationScene/rules/AutoAssignmentRules'
import { CustomGroupingRules } from '@posthog/products-error-tracking/frontend/scenes/ErrorTrackingConfigurationScene/rules/CustomGroupingRules'
import { SymbolSets } from '@posthog/products-error-tracking/frontend/scenes/ErrorTrackingConfigurationScene/symbol_sets/SymbolSets'
import { EventConfiguration } from '@posthog/products-revenue-analytics/frontend/settings/EventConfiguration'
import { ExternalDataSourceConfiguration } from '@posthog/products-revenue-analytics/frontend/settings/ExternalDataSourceConfiguration'
import { FilterTestAccountsConfiguration as RevenueAnalyticsFilterTestAccountsConfiguration } from '@posthog/products-revenue-analytics/frontend/settings/FilterTestAccountsConfiguration'
import { GoalsConfiguration } from '@posthog/products-revenue-analytics/frontend/settings/GoalsConfiguration'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { FEATURE_SUPPORT } from 'lib/components/SupportedPlatforms/featureSupport'
import { OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { BounceRateDurationSetting } from 'scenes/settings/environment/BounceRateDuration'
import { BounceRatePageViewModeSetting } from 'scenes/settings/environment/BounceRatePageViewMode'
import { CookielessServerHashModeSetting } from 'scenes/settings/environment/CookielessServerHashMode'
import { CustomChannelTypes } from 'scenes/settings/environment/CustomChannelTypes'
import { DeadClicksAutocaptureSettings } from 'scenes/settings/environment/DeadClicksAutocaptureSettings'
import { MaxChangelogSettings } from 'scenes/settings/environment/MaxChangelogSettings'
import { MaxMemorySettings } from 'scenes/settings/environment/MaxMemorySettings'
import { PersonsJoinMode } from 'scenes/settings/environment/PersonsJoinMode'
import { PersonsOnEvents } from 'scenes/settings/environment/PersonsOnEvents'
import { PreAggregatedTablesSetting } from 'scenes/settings/environment/PreAggregatedTablesSetting'
import { ReplayTriggers } from 'scenes/settings/environment/ReplayTriggers'
import { SessionsTableVersion } from 'scenes/settings/environment/SessionsTableVersion'
import { SessionsV2JoinModeSettings } from 'scenes/settings/environment/SessionsV2JoinModeSettings'
import { urls } from 'scenes/urls'

import {
    DefaultRoleSelector,
    RolesAccessControls,
} from '~/layout/navigation-3000/sidepanel/panels/access_control/RolesAccessControls'
import { AccessControlLevel, AccessControlResourceType, Realm } from '~/types'

import { CustomerAnalyticsDashboardEvents } from 'products/customer_analytics/frontend/scenes/CustomerAnalyticsConfigurationScene/events/CustomerAnalyticsDashboardEvents'
import {
    ExceptionAutocaptureToggle,
    ExceptionIngestionControls,
    ExceptionSuppressionRules,
} from 'products/error_tracking/frontend/scenes/ErrorTrackingConfigurationScene/exception_autocapture/ExceptionAutocaptureSettings'

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
import { DefaultExperimentConfidenceLevel } from './environment/DefaultExperimentConfidenceLevel'
import { DefaultExperimentStatsMethod } from './environment/DefaultExperimentStatsMethod'
import { DiscussionMentionNotifications } from './environment/DiscussionSettings'
import { ErrorTrackingIntegrations } from './environment/ErrorTrackingIntegrations'
import { ExperimentRecalculationTime } from './environment/ExperimentRecalculationTime'
import {
    DefaultEvaluationContexts,
    FlagChangeConfirmationSettings,
    FlagPersistenceSettings,
    FlagsSecureApiKeys,
    RequireEvaluationContexts,
} from './environment/FeatureFlagSettings'
import { FeaturePreviewsComingSoon, FeaturePreviewsSettings } from './environment/FeaturePreviewsSettings'
import { GroupAnalyticsConfig } from './environment/GroupAnalyticsConfig'
import { HeatmapsSettings } from './environment/HeatmapsSettings'
import { HumanFriendlyComparisonPeriodsSetting } from './environment/HumanFriendlyComparisonPeriodsSetting'
import { IPAllowListInfo } from './environment/IPAllowListInfo'
import { IPCapture } from './environment/IPCapture'
import { GithubIntegration, LinearIntegration } from './environment/Integrations'
import { LogsCaptureSettings, LogsJsonParseSettings, LogsRetentionSettings } from './environment/LogsCaptureSettings'
import MCPServerSettings from './environment/MCPServerSettings'
import { ManagedReverseProxy } from './environment/ManagedReverseProxy'
import { MarketingAnalyticsSettingsWrapper } from './environment/MarketingAnalyticsSettingsWrapper'
import { PathCleaningFiltersConfig } from './environment/PathCleaningFiltersConfig'
import { PersonDisplayNameProperties } from './environment/PersonDisplayNameProperties'
import { ReplayIntegrations } from './environment/ReplayIntegrations'
import {
    CanvasCaptureSettings,
    LogCaptureSettings,
    ReplayAuthorizedDomains,
    ReplayDataRetentionSettings,
    ReplayGeneral,
    ReplayMaskingSettings,
    ReplayNetworkCapture,
    ReplayNetworkHeadersPayloads,
} from './environment/SessionRecordingSettings'
import { SlackIntegration } from './environment/SlackIntegration'
import { SurveyDefaultAppearance, SurveyEnableToggle } from './environment/SurveySettings'
import { TeamAccessControl } from './environment/TeamAccessControl'
import { TeamDangerZone } from './environment/TeamDangerZone'
import {
    TeamAuthorizedURLs,
    TeamBusinessModel,
    TeamDisplayName,
    TeamTimezone,
    TeamVariables,
    WebSnippet,
    WebSnippetV2,
} from './environment/TeamSettings'
import { ProjectAccountFiltersSetting } from './environment/TestAccountFiltersConfig'
import { UsageMetricsConfig } from './environment/UsageMetricsConfig'
import { WebAnalyticsEnablePreAggregatedTables } from './environment/WebAnalyticsAPISetting'
import { WebhookIntegration } from './environment/WebhookIntegration'
import { ApprovalPolicies } from './organization/Approvals/ApprovalPolicies'
import { ChangeRequestsList } from './organization/Approvals/ChangeRequestsList'
import { Invites } from './organization/Invites'
import { Members } from './organization/Members'
import { MembersPlatformAddonAd } from './organization/MembersPlatformAddonAd'
import { OrganizationAI } from './organization/OrgAI'
import { OrganizationDisplayName } from './organization/OrgDisplayName'
import { OrganizationEmailPreferences } from './organization/OrgEmailPreferences'
import { OrgIPAnonymizationDefault } from './organization/OrgIPAnonymizationDefault'
import { OrganizationDangerZone } from './organization/OrganizationDangerZone'
import { OrganizationIntegrations } from './organization/OrganizationIntegrations'
import { OrganizationSecuritySettings } from './organization/OrganizationSecuritySettings'
import { VerifiedDomains } from './organization/VerifiedDomains/VerifiedDomains'
import { ProjectDangerZone } from './project/ProjectDangerZone'
import { ProjectMove } from './project/ProjectMove'
import { ProjectDisplayName } from './project/ProjectSettings'
import { SettingSection } from './types'
import { AllowImpersonation } from './user/AllowImpersonation'
import { ChangePassword, ChangePasswordTitle } from './user/ChangePassword'
import { HedgehogModeSettings } from './user/HedgehogModeSettings'
import { OptOutCapture } from './user/OptOutCapture'
import { PasskeySettings } from './user/PasskeySettings'
import { PersonalAPIKeys } from './user/PersonalAPIKeys'
import { SqlEditorTabPreference } from './user/SqlEditorTabPreference'
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
                id: 'variables',
                title: 'Project API key & ID',
                description: 'Your project API key and ID used to connect SDKs and APIs to this environment.',
                component: <TeamVariables />,
                keywords: ['api key', 'token', 'project id'],
            },
            {
                id: 'snippet',
                title: 'Web snippet',
                description:
                    "Add this JavaScript snippet to your website's HTML, ideally just above the </head> tag, to start capturing events, recording sessions, and more.",
                docsUrl: 'https://posthog.com/docs/getting-started/install?tab=snippet',
                component: <WebSnippet />,
                keywords: ['javascript', 'install', 'setup', 'tracking', 'code'],
            },
            {
                id: 'snippet-v2',
                title: (
                    <>
                        Web snippet V2{' '}
                        <LemonTag type="warning" className="ml-1 uppercase">
                            Experimental
                        </LemonTag>
                    </>
                ),
                description:
                    'The V2 snippet includes your project config automatically along with the PostHog JS code, leading to faster load times and fewer calls needed before the SDK is fully functional.',
                flag: 'REMOTE_CONFIG',
                component: <WebSnippetV2 />,
                keywords: ['javascript', 'install', 'setup', 'v2', 'fast'],
            },
            {
                id: 'authorized-urls',
                title: 'Toolbar authorized URLs',
                description:
                    'URLs where the PostHog toolbar will load and where web analytics and web experiments data is collected from. Wildcards are not allowed — URLs must be concrete and launchable.',
                docsUrl: 'https://posthog.com/docs/toolbar',
                component: <TeamAuthorizedURLs />,
                keywords: ['domain', 'whitelist', 'allowlist'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-customization',
        title: 'Customization',
        settings: [
            {
                id: 'display-name',
                title: 'Display name',
                description: 'A human-friendly name for this environment.',
                component: <TeamDisplayName />,
                keywords: ['name', 'rename', 'label'],
            },
            {
                id: 'date-and-time',
                title: 'Date & time',
                description:
                    'Set the timezone and week start day used for displaying and bucketing time-series data in insights and dashboards. You may need to refresh insights for changes to apply.',
                component: <TeamTimezone />,
                keywords: ['timezone', 'utc', 'locale', 'week start'],
            },
            {
                id: 'business-model',
                title: 'Business model',
                description:
                    'Set whether this project serves B2B or B2C customers so PostHog can tailor the experience and recommendations.',
                component: <TeamBusinessModel />,
                keywords: ['b2b', 'b2c', 'saas', 'ecommerce'],
            },
            {
                id: 'base-currency',
                title: 'Base currency',
                description: 'Set the default currency used for revenue and monetary calculations.',
                component: <BaseCurrency hideTitle />,
                keywords: ['money', 'currency', 'usd', 'eur'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-autocapture',
        title: 'Autocapture',
        settings: [
            {
                id: 'autocapture',
                title: 'Autocapture',
                description:
                    'Automatically capture frontend events such as clicks, input changes, and form submissions when using the web JavaScript SDK. Also available for React Native and iOS via code configuration.',
                docsUrl: 'https://posthog.com/docs/product-analytics/autocapture',
                platformSupport: FEATURE_SUPPORT.autocapture,
                component: <AutocaptureSettings />,
                keywords: ['click', 'input', 'form', 'dom', 'automatic', 'event'],
            },
            {
                id: 'autocapture-data-attributes',
                title: 'Data attributes',
                description:
                    'Specify data attributes used in your app (e.g. data-attr, data-custom-id). These attributes help the toolbar and action definitions match unique elements on your pages. Use * as a wildcard.',
                docsUrl: 'https://posthog.com/docs/product-analytics/autocapture#data-attributes',
                component: <DataAttributes />,
                keywords: ['selector', 'css', 'element', 'toolbar', 'action'],
            },
            {
                id: 'web-vitals-autocapture',
                title: 'Web vitals autocapture',
                description:
                    "Capture Google Chrome's web vitals metrics (LCP, CLS, FCP, INP). These events enhance web analytics and session replay with performance data.",
                docsUrl: 'https://posthog.com/docs/web-analytics/web-vitals',
                platformSupport: FEATURE_SUPPORT.webVitals,
                component: <WebVitalsAutocaptureSettings />,
                keywords: ['lcp', 'cls', 'fid', 'inp', 'fcp', 'performance', 'core web vitals'],
            },
            {
                id: 'dead-clicks-autocapture',
                title: 'Dead clicks autocapture',
                description:
                    "Track clicks that don't result in any action (no scroll, text selection, or DOM mutation). Dead clicks help you find elements users expect to be interactive but aren't.",
                docsUrl: 'https://posthog.com/docs/toolbar/heatmaps#dead-clicks',
                platformSupport: FEATURE_SUPPORT.deadClicks,
                component: <DeadClicksAutocaptureSettings />,
                keywords: ['rage click', 'broken', 'unresponsive', 'frustration'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-max',
        title: 'PostHog AI',
        group: 'AI',
        settings: [
            {
                id: 'core-memory',
                title: 'Memory',
                description:
                    "PostHog AI automatically remembers details about your company and product. This context helps our AI assistant provide relevant answers and suggestions. If there are any details you don't want PostHog AI to remember, you can edit or remove them below.",
                component: <MaxMemorySettings />,
                hideOn: [Realm.SelfHostedClickHouse, Realm.SelfHostedPostgres],
            },
            {
                id: 'changelog',
                title: 'Changelog',
                description:
                    'See the latest PostHog AI features and control whether the changelog appears in the main UI.',
                component: <MaxChangelogSettings />,
                hideOn: [Realm.SelfHostedClickHouse, Realm.SelfHostedPostgres],
            },
        ],
    },
    {
        level: 'environment',
        id: 'mcp-server',
        title: 'MCP server',
        group: 'AI',
        settings: [
            {
                id: 'mcp-server-configure',
                title: 'Model Context Protocol (MCP) server',
                description:
                    'Connect PostHog to AI tools like Claude, Cursor, and Copilot via the MCP protocol for data-driven AI assistance.',
                docsUrl: 'https://posthog.com/docs/model-context-protocol',
                component: <MCPServerSettings />,
                keywords: ['ai', 'llm', 'claude', 'cursor', 'copilot'],
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
                description:
                    'Collect Content Security Policy violation reports to monitor and debug CSP issues on your site.',
                component: <CSPReportingSettings />,
                keywords: ['content security policy', 'csp', 'violation', 'security'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-customer-analytics',
        title: 'Customer analytics',
        flag: 'CUSTOMER_ANALYTICS',
        group: 'Products',
        settings: [
            {
                id: 'group-analytics',
                title: 'Group analytics',
                description: 'Configure group types for analyzing user behavior at the company or team level.',
                docsUrl: 'https://posthog.com/docs/product-analytics/group-analytics',
                component: <GroupAnalyticsConfig />,
                keywords: ['company', 'organization', 'team', 'group type'],
            },
            {
                id: 'customer-analytics-usage-metrics',
                title: 'Usage metrics',
                description: 'Configure which events and properties are tracked as usage metrics for your customers.',
                component: <UsageMetricsConfig />,
                flag: 'CUSTOMER_ANALYTICS',
                keywords: ['usage', 'engagement', 'activity'],
            },
            {
                id: 'customer-analytics-dashboard-events',
                title: 'Dashboard events',
                description: 'Configure which events appear on customer analytics dashboards.',
                component: <CustomerAnalyticsDashboardEvents />,
                flag: 'CUSTOMER_ANALYTICS',
                keywords: ['dashboard', 'customer', 'events'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-product-analytics',
        title: 'Product analytics',
        group: 'Products',
        settings: [
            {
                id: 'internal-user-filtering',
                title: 'Filter out internal and test users',
                description:
                    'Define filters to exclude internal users and test accounts from your analytics. Filtered users will not appear in insights by default.',
                docsUrl: 'https://posthog.com/tutorials/filter-internal-users',
                component: <ProjectAccountFiltersSetting />,
                keywords: ['test account', 'internal', 'exclude', 'filter'],
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
                description: 'Customize the color palette used in charts and visualizations.',
                component: <DataColorThemes />,
                keywords: ['color', 'palette', 'chart', 'visualization'],
            },
            {
                id: 'persons-on-events',
                title: 'Person properties mode',
                description:
                    'Choose the behavior of person property filters. For best performance, use person properties from the time of the event.',
                component: <PersonsOnEvents />,
                flag: '!SETTINGS_PERSONS_ON_EVENTS_HIDDEN', // Setting hidden for Cloud orgs created since June 2024
                keywords: ['person', 'properties', 'join', 'query', 'performance'],
            },
            {
                id: 'correlation-analysis',
                title: 'Correlation analysis exclusions',
                description:
                    'Correlation analysis automatically surfaces relevant signals for conversion. Exclude events or properties that do not provide useful signals.',
                docsUrl: 'https://posthog.com/docs/product-analytics/funnels#correlation-analysis',
                component: <CorrelationConfig />,
                keywords: ['funnel', 'conversion', 'exclude', 'property'],
            },
            {
                id: 'person-display-name',
                title: 'Person display name',
                description:
                    'Choose which person properties are used to display names in the UI (e.g. email, name, username).',
                docsUrl: 'https://posthog.com/docs/data/persons',
                component: <PersonDisplayNameProperties />,
                keywords: ['name', 'email', 'identity', 'display'],
            },
            {
                id: 'path-cleaning',
                title: 'Path cleaning rules',
                description:
                    'Define regex rules to normalize URLs in path analysis. Useful for removing IDs or query parameters from paths.',
                docsUrl: 'https://posthog.com/docs/product-analytics/paths#path-cleaning-rules',
                component: <PathCleaningFiltersConfig />,
                keywords: ['url', 'regex', 'normalize', 'path analysis'],
            },
            {
                id: 'human-friendly-comparison-periods',
                title: 'Human friendly comparison periods',
                description:
                    'When comparing against a previous month or year, compare against the same day of the week instead of the same calendar date. A year comparison becomes 52 weeks, and a month comparison becomes 4 weeks.',
                component: <HumanFriendlyComparisonPeriodsSetting />,
                keywords: ['compare', 'period', 'week', 'month', 'year', 'seasonality'],
            },
            {
                id: 'group-analytics',
                title: 'Group analytics',
                description: 'Configure group types for analyzing user behavior at the company or team level.',
                docsUrl: 'https://posthog.com/docs/product-analytics/group-analytics',
                component: <GroupAnalyticsConfig />,
                flag: '!CUSTOMER_ANALYTICS',
                keywords: ['company', 'organization', 'team', 'group type'],
            },
            {
                id: 'persons-join-mode',
                title: 'Persons join mode',
                description:
                    'Choose how persons are joined to events. Do not change this setting unless you know what you are doing.',
                component: <PersonsJoinMode />,
                flag: 'SETTINGS_PERSONS_JOIN_MODE',
                keywords: ['join', 'inner', 'left', 'personless'],
            },
            {
                id: 'session-table-version',
                title: 'Sessions table version',
                description:
                    'Choose which version of the sessions table to use. V2 is faster but requires uuidv7 session IDs. Use auto unless you know what you are doing.',
                component: <SessionsTableVersion />,
                flag: 'SETTINGS_SESSION_TABLE_VERSION',
                keywords: ['session', 'table', 'version', 'uuidv7'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-privacy',
        title: 'Privacy',
        settings: [
            {
                id: 'datacapture',
                title: 'IP data capture configuration',
                description:
                    'When enabled, client IP addresses will not be stored with your events. Transformations like GeoIP enrichment and bot detection can still use the IP before it is discarded.',
                docsUrl: 'https://posthog.com/docs/privacy',
                component: <IPCapture />,
                keywords: ['ip', 'anonymize', 'gdpr', 'privacy', 'geolocation', 'discard'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-revenue-analytics',
        title: 'Revenue analytics',
        group: 'Products',
        accessControl: {
            resourceType: AccessControlResourceType.RevenueAnalytics,
            minimumAccessLevel: AccessControlLevel.Editor,
        },
        settings: [
            {
                id: 'revenue-base-currency',
                title: 'Base currency',
                description: 'Set the base currency for revenue analytics calculations.',
                component: (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.RevenueAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <BaseCurrency hideTitle />
                    </AccessControlAction>
                ),
                hideWhenNoSection: true,
                keywords: ['money', 'currency', 'usd', 'eur'],
            },
            {
                id: 'revenue-analytics-filter-test-accounts',
                title: 'Filter out internal and test users from revenue analytics',
                description: 'Exclude test accounts from revenue calculations and reports.',
                component: <RevenueAnalyticsFilterTestAccountsConfiguration />,
                keywords: ['test account', 'internal', 'exclude', 'filter', 'revenue'],
            },
            {
                id: 'revenue-analytics-goals',
                title: 'Revenue goals',
                description: 'Set revenue targets to track performance against your business objectives.',
                component: <GoalsConfiguration />,
                keywords: ['target', 'mrr', 'arr', 'goal'],
            },
            {
                id: 'revenue-analytics-events',
                title: 'Revenue events',
                description: 'Configure which events represent revenue-generating actions.',
                docsUrl: 'https://posthog.com/docs/revenue-analytics',
                component: <EventConfiguration />,
                keywords: ['purchase', 'payment', 'subscription', 'charge'],
            },
            {
                id: 'revenue-analytics-external-data-sources',
                title: 'External data sources',
                description: 'Connect external data sources like Stripe for revenue tracking.',
                component: <ExternalDataSourceConfiguration />,
                keywords: ['stripe', 'import', 'sync', 'data warehouse'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-marketing-analytics',
        title: 'Marketing analytics',
        flag: 'WEB_ANALYTICS_MARKETING',
        group: 'Products',
        settings: [
            {
                id: 'marketing-settings',
                title: 'Marketing settings',
                description: 'Configure tracking and attribution settings for marketing analytics.',
                docsUrl: 'https://posthog.com/docs/web-analytics/marketing-analytics',
                component: <MarketingAnalyticsSettingsWrapper />,
                keywords: ['utm', 'attribution', 'campaign', 'channel', 'marketing'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-web-analytics',
        title: 'Web analytics',
        group: 'Products',
        settings: [
            {
                id: 'web-analytics-authorized-urls',
                title: 'Web analytics domains',
                description:
                    'Configure which domains are tracked in web analytics. Wildcards are not allowed — URLs must be concrete and launchable.',
                component: <TeamAuthorizedURLs />,
                keywords: ['domain', 'website', 'url'],
            },
            {
                id: 'channel-type',
                title: 'Custom channel type',
                description: 'Define custom rules for categorizing traffic sources into channels.',
                docsUrl: 'https://posthog.com/docs/data/channel-type',
                component: <CustomChannelTypes />,
                keywords: ['utm', 'source', 'medium', 'referrer', 'attribution'],
            },
            {
                id: 'cookieless-server-hash-mode',
                title: 'Cookieless server hash mode',
                description:
                    'Enable cookieless tracking using a privacy-preserving hash to count unique users without cookies. You must enable this here before enabling cookieless in posthog-js.',
                docsUrl: 'https://posthog.com/docs/web-analytics/cookieless-tracking',
                component: <CookielessServerHashModeSetting />,
                keywords: ['cookie', 'privacy', 'gdpr', 'tracking', 'consent'],
            },
            {
                id: 'bounce-rate-duration',
                title: 'Bounce rate duration',
                description:
                    'Set how long a user can stay on a page (in seconds) before the session is not counted as a bounce. Default is 10 seconds.',
                docsUrl: 'https://posthog.com/docs/web-analytics/bounce-rate',
                component: <BounceRateDurationSetting />,
                keywords: ['bounce', 'session', 'duration', 'seconds'],
            },
            {
                id: 'bounce-rate-page-view-mode',
                title: 'Bounce rate page view mode',
                description:
                    'Choose how pageviews are counted as part of the bounce rate calculation. Other factors like autocaptures and session duration are also considered.',
                component: <BounceRatePageViewModeSetting />,
                flag: 'SETTINGS_BOUNCE_RATE_PAGE_VIEW_MODE',
                keywords: ['bounce', 'pageview', 'url', 'calculation'],
            },
            {
                id: 'session-join-mode',
                title: 'Session join mode',
                description:
                    "Choose which join mode to use for sessions. Don't change this unless you know what you're doing.",
                component: <SessionsV2JoinModeSettings />,
                flag: 'SETTINGS_SESSIONS_V2_JOIN',
                keywords: ['session', 'join', 'string', 'uuid'],
            },
            {
                id: 'web-analytics-pre-aggregated-tables',
                title: 'Pre-aggregated tables',
                description: 'Configure pre-aggregated tables to speed up web analytics queries.',
                component: <PreAggregatedTablesSetting />,
                flag: 'SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES',
                keywords: ['performance', 'speed', 'query', 'materialized'],
            },
            {
                id: 'web-analytics-opt-in-pre-aggregated-tables-and-api',
                title: 'New query engine',
                description: 'Enable the new pre-aggregated query engine for faster web analytics.',
                component: <WebAnalyticsEnablePreAggregatedTables />,
                flag: 'WEB_ANALYTICS_API',
                keywords: ['performance', 'speed', 'query', 'api'],
            },
            {
                id: 'web-vitals-autocapture',
                title: 'Web vitals autocapture',
                description: "Capture Google Chrome's web vitals metrics for web analytics performance tracking.",
                docsUrl: 'https://posthog.com/docs/web-analytics/web-vitals',
                platformSupport: FEATURE_SUPPORT.webVitals,
                component: <WebVitalsAutocaptureSettings />,
                keywords: ['lcp', 'cls', 'fcp', 'inp', 'performance', 'core web vitals'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-replay',
        title: 'Session replay',
        group: 'Products',
        settings: [
            {
                id: 'replay',
                title: 'Session replay',
                description:
                    'Watch recordings of how users interact with your web app to diagnose issues and understand user behavior.',
                docsUrl: 'https://posthog.com/docs/session-replay',
                component: <ReplayGeneral />,
                keywords: ['recording', 'video', 'screen', 'session'],
            },
            {
                id: 'replay-log-capture',
                title: 'Log capture',
                description: 'Capture browser console logs alongside session recordings to help debug issues.',
                docsUrl: 'https://posthog.com/docs/session-replay/console-log-recording',
                platformSupport: FEATURE_SUPPORT.sessionReplayLogCapture,
                component: <LogCaptureSettings />,
                keywords: ['console', 'log', 'debug', 'error'],
            },
            {
                id: 'replay-canvas-capture',
                title: 'Canvas capture',
                description:
                    'Capture HTML canvas elements in session recordings. Useful for apps that render charts, games, or other canvas-based content.',
                docsUrl: 'https://posthog.com/docs/session-replay/canvas-recording',
                platformSupport: FEATURE_SUPPORT.sessionReplayCanvasCapture,
                component: <CanvasCaptureSettings />,
                keywords: ['canvas', 'webgl', 'drawing', 'chart'],
            },
            {
                id: 'replay-triggers',
                title: 'Recording conditions',
                description:
                    'Control when recordings start and stop. Use URL triggers, event triggers, or sampling to manage recording volume.',
                docsUrl: 'https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record',
                component: <ReplayTriggers />,
                keywords: ['trigger', 'url', 'event', 'sample', 'condition', 'filter'],
            },
            {
                id: 'replay-masking',
                title: 'Privacy and masking',
                description:
                    'Choose what data gets masked in your session recordings. For more control, configure masking directly in your code.',
                docsUrl: 'https://posthog.com/docs/session-replay/privacy',
                platformSupport: FEATURE_SUPPORT.sessionReplayMasking,
                component: <ReplayMaskingSettings />,
                keywords: ['redact', 'sensitive', 'pii', 'hide', 'mask', 'privacy', 'gdpr'],
            },
            {
                id: 'replay-network',
                title: 'Network capture',
                description:
                    'Capture network request timings alongside session recordings to identify slow or failing API calls.',
                docsUrl: 'https://posthog.com/docs/session-replay/network-recording',
                platformSupport: FEATURE_SUPPORT.sessionReplayCaptureRequests,
                component: <ReplayNetworkCapture />,
                keywords: ['xhr', 'fetch', 'api', 'request', 'response', 'performance'],
            },
            {
                id: 'replay-network-headers-payloads',
                title: 'Network headers & payloads',
                description:
                    'Capture request and response headers and body content alongside network timings. Sensitive data is automatically scrubbed.',
                docsUrl: 'https://posthog.com/docs/session-replay/network-recording',
                platformSupport: FEATURE_SUPPORT.sessionReplayCaptureHeadersAndPayloads,
                component: <ReplayNetworkHeadersPayloads />,
                keywords: ['headers', 'payload', 'body', 'request', 'response'],
            },
            {
                id: 'web-vitals-autocapture',
                title: 'Web vitals',
                description: 'Capture web vitals metrics alongside session recordings for performance analysis.',
                docsUrl: 'https://posthog.com/docs/web-analytics/web-vitals',
                platformSupport: FEATURE_SUPPORT.webVitals,
                component: <WebVitalsAutocaptureSettings />,
                keywords: ['lcp', 'cls', 'fcp', 'inp', 'performance'],
            },
            {
                id: 'replay-authorized-domains',
                title: 'Authorized domains for replay',
                description:
                    'This setting is deprecated. Use URL triggers in recording conditions to control which domains are recorded.',
                platformSupport: FEATURE_SUPPORT.sessionReplayAuthorizedDomains,
                component: <ReplayAuthorizedDomains />,
                allowForTeam: (t) => !!t?.recording_domains?.length,
                keywords: ['domain', 'whitelist', 'allowlist'],
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
                description:
                    'Control how long your recordings are stored. Changes only affect the retention period for future recordings.',
                component: <ReplayDataRetentionSettings />,
                keywords: ['storage', 'retention', 'delete', 'days', 'months'],
            },
            {
                id: 'replay-integrations',
                title: (
                    <>
                        Integrations
                        <LemonTag type="success" className="ml-1 uppercase">
                            New
                        </LemonTag>
                    </>
                ),
                description: 'Configure integrations to create and link issues from session replays.',
                component: <ReplayIntegrations />,
                keywords: ['integration', 'connect', 'third-party'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-heatmaps',
        title: 'Heatmaps',
        group: 'Products',
        settings: [
            {
                id: 'heatmaps',
                title: 'Heatmaps',
                description:
                    'Capture general clicks, mouse movements, and scrolling to create heatmaps. No additional events are created. Heatmaps are generated based on overall mouse or touch positions, useful for understanding general user behavior.',
                docsUrl: 'https://posthog.com/docs/toolbar/heatmaps',
                platformSupport: FEATURE_SUPPORT.heatmaps,
                component: <HeatmapsSettings />,
                keywords: ['click map', 'scroll', 'rage click', 'mouse', 'touch'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-surveys',
        title: 'Surveys',
        group: 'Products',
        settings: [
            {
                id: 'surveys-interface',
                title: 'Surveys',
                description:
                    'Enable or disable surveys in your web application. When disabled, surveys will not be rendered automatically.',
                docsUrl: 'https://posthog.com/docs/surveys',
                platformSupport: FEATURE_SUPPORT.surveys,
                component: <SurveyEnableToggle />,
                keywords: ['popup', 'widget', 'feedback', 'nps', 'csat', 'enable'],
            },
            {
                id: 'surveys-default-appearance',
                title: 'Default survey appearance',
                description:
                    'Configure the default look and feel for new surveys. Individual surveys can override these settings.',
                docsUrl: 'https://posthog.com/docs/surveys/creating-surveys#customizing-the-look-and-feel',
                component: <SurveyDefaultAppearance />,
                keywords: ['appearance', 'style', 'theme', 'customization', 'popup'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-feature-flags',
        title: 'Feature flags',
        group: 'Products',
        settings: [
            {
                id: 'feature-flags-interface',
                title: 'Flag persistence',
                description:
                    'When enabled, all new feature flags will have persistence enabled by default. This ensures consistent user experiences across authentication steps.',
                docsUrl:
                    'https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps',
                component: <FlagPersistenceSettings />,
                keywords: ['flag', 'persistence', 'authentication', 'consistent'],
            },
            {
                id: 'feature-flag-confirmation',
                title: 'Flag change confirmation',
                description:
                    'Show a confirmation modal before saving changes to existing feature flags, helping prevent accidental changes to release conditions.',
                component: <FlagChangeConfirmationSettings />,
                keywords: ['confirmation', 'safety', 'change', 'release'],
            },
            {
                id: 'feature-flag-require-evaluation-contexts',
                title: 'Require evaluation contexts',
                description:
                    'Require all new feature flags to have at least one evaluation context before they can be created, preventing flags that are not properly scoped.',
                docsUrl: 'https://posthog.com/docs/feature-flags/evaluation-contexts',
                flag: 'FLAG_EVALUATION_TAGS',
                component: <RequireEvaluationContexts />,
                keywords: ['evaluation', 'context', 'scope', 'require'],
            },
            {
                id: 'feature-flag-default-evaluation-contexts',
                title: 'Default evaluation contexts',
                description:
                    'Automatically apply default evaluation context tags to newly created feature flags. Users can still modify them during flag creation.',
                docsUrl: 'https://posthog.com/docs/feature-flags/evaluation-contexts',
                flag: 'DEFAULT_EVALUATION_ENVIRONMENTS',
                component: <DefaultEvaluationContexts />,
                keywords: ['evaluation', 'default', 'context', 'tag'],
            },
            {
                id: 'feature-flag-secure-api-key',
                title: 'Feature flags secure API key',
                description:
                    'Use this key for local evaluation of feature flags or remote config settings. Replaces personal API keys for local evaluation.',
                docsUrl: 'https://posthog.com/docs/feature-flags/local-evaluation',
                component: <FlagsSecureApiKeys />,
                keywords: ['api key', 'secret', 'local evaluation', 'remote config'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-experiments',
        title: 'Experiments',
        group: 'Products',
        settings: [
            {
                id: 'environment-experiment-stats-method',
                title: 'Default statistical method',
                description:
                    'Choose which statistical method to use by default for new experiments in this environment. Individual experiments can override this setting.',
                docsUrl: 'https://posthog.com/docs/experiments',
                component: <DefaultExperimentStatsMethod />,
                keywords: ['bayesian', 'frequentist', 'statistics', 'ab test'],
            },
            {
                id: 'environment-experiment-confidence-level',
                title: 'Default confidence level',
                description:
                    'Higher confidence level reduces false positives but requires more data. Can be overridden per experiment.',
                component: <DefaultExperimentConfidenceLevel />,
                keywords: ['confidence', 'significance', 'p-value', 'false positive'],
            },
            {
                id: 'environment-experiment-recalculation-time',
                title: 'Daily recalculation time',
                description:
                    "Select the time of day when experiment metrics should be recalculated. This time is in your project's timezone.",
                component: <ExperimentRecalculationTime />,
                keywords: ['schedule', 'refresh', 'update', 'time'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-error-tracking',
        title: 'Error tracking',
        group: 'Products',
        settings: [
            {
                id: 'error-tracking-exception-autocapture',
                title: 'Exception autocapture',
                description:
                    'Automatically capture frontend exceptions using onError and onUnhandledRejection listeners in the web JavaScript SDK.',
                docsUrl: 'https://posthog.com/docs/error-tracking',
                platformSupport: FEATURE_SUPPORT.errorTrackingExceptionAutocapture,
                component: <ExceptionAutocaptureToggle />,
                keywords: ['crash', 'bug', 'exception', 'stack trace'],
            },
            {
                id: 'error-tracking-suppression-rules',
                title: 'Suppression rules',
                description:
                    'Filter autocaptured exceptions by type or message to skip capturing certain exceptions in the web SDK.',
                platformSupport: FEATURE_SUPPORT.errorTrackingSuppressionRules,
                component: <ExceptionSuppressionRules />,
                keywords: ['filter', 'ignore', 'suppress', 'exception', 'type', 'message'],
            },
            {
                id: 'error-tracking-ingestion-controls',
                title: 'Autocapture controls',
                description: 'Selectively enable exception autocapture based on the user or scenario.',
                platformSupport: FEATURE_SUPPORT.errorTrackingSuppressionRules,
                component: <ExceptionIngestionControls />,
                flag: 'ERROR_TRACKING_INGESTION_CONTROLS',
                keywords: ['ingestion', 'control', 'selective', 'autocapture'],
            },
            {
                id: 'error-tracking-alerting',
                title: 'Alerting',
                description: 'Configure alerts to get notified when new errors occur or error rates spike.',
                component: <ErrorTrackingAlerting />,
                keywords: ['notification', 'alert', 'threshold', 'spike'],
            },
            {
                id: 'error-tracking-auto-assignment',
                title: 'Auto assignment rules',
                description: 'Automatically assign errors to team members based on rules you define.',
                component: <AutoAssignmentRules />,
                keywords: ['assign', 'owner', 'team', 'rule', 'routing'],
            },
            {
                id: 'error-tracking-custom-grouping',
                title: 'Custom grouping rules',
                description: 'Define rules for how errors are grouped together into issues.',
                component: <CustomGroupingRules />,
                keywords: ['group', 'merge', 'fingerprint', 'dedup'],
            },
            {
                id: 'error-tracking-integrations',
                title: 'Integrations',
                description: 'Connect error tracking with external services like Sentry or PagerDuty.',
                component: <ErrorTrackingIntegrations />,
                keywords: ['sentry', 'pagerduty', 'integration', 'connect'],
            },
            {
                id: 'error-tracking-symbol-sets',
                title: 'Symbol sets',
                description: 'Upload source maps to get readable stack traces from minified code.',
                docsUrl: 'https://posthog.com/docs/error-tracking/source-maps',
                component: <SymbolSets />,
                keywords: ['source map', 'sourcemap', 'debug', 'minified', 'stack trace'],
            },
            {
                id: 'error-tracking-releases',
                title: 'Releases',
                description: 'Track releases to see which version introduced errors and monitor deployment health.',
                docsUrl: 'https://posthog.com/docs/error-tracking/releases',
                component: <Releases />,
                keywords: ['version', 'deploy', 'release', 'regression'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-logs',
        title: 'Logs',
        flag: 'LOGS_SETTINGS',
        group: 'Products',
        settings: [
            {
                id: 'logs',
                title: 'Logs',
                description:
                    'Automatically capture browser console logs and send them to the Logs product for analysis and debugging. This is separate from session replay console log capture.',
                docsUrl: 'https://posthog.com/docs/logs',
                platformSupport: FEATURE_SUPPORT.logsCapture,
                component: <LogsCaptureSettings />,
                flag: 'LOGS_SETTINGS',
                keywords: ['log', 'capture', 'collect', 'ingest', 'console'],
            },
            {
                id: 'logs-json-parse',
                title: 'JSON parse logs',
                description:
                    'Parse log lines that are valid JSON and add their fields as log attributes that can be used in filters.',
                component: <LogsJsonParseSettings />,
                flag: 'LOGS_SETTINGS_JSON',
                keywords: ['json', 'parse', 'structured', 'format'],
            },
            {
                id: 'logs-retention',
                title: 'Retention',
                description:
                    'How long to retain logs before they are automatically deleted. You can only change this setting at most once per 24 hours.',
                component: <LogsRetentionSettings />,
                flag: 'LOGS_SETTINGS_RETENTION',
                keywords: ['retention', 'storage', 'delete', 'ttl'],
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
                description: 'Manage who has access to this environment and what they can do.',
                docsUrl: 'https://posthog.com/docs/settings/access-control',
                component: <TeamAccessControl />,
                keywords: ['permission', 'role', 'access', 'rbac', 'team'],
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
                description: 'View a log of changes made to this environment by team members.',
                component: <ActivityLogSettings />,
                keywords: ['audit', 'history', 'change', 'activity'],
            },
            {
                id: 'activity-log-org-level-settings',
                title: 'Settings',
                description: 'Configure organization-level activity log settings.',
                component: <ActivityLogOrgLevelSettings />,
                keywords: ['audit', 'organization', 'activity'],
            },
            {
                id: 'activity-log-notifications',
                title: 'Notifications',
                description: 'Get notified about activity log events via configured destinations.',
                component: <ActivityLogNotifications />,
                flag: 'CDP_ACTIVITY_LOG_NOTIFICATIONS',
                keywords: ['notification', 'alert', 'activity', 'webhook'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-approvals',
        title: 'Approvals',
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        settings: [
            {
                id: 'approval-policies',
                title: 'Policies',
                description: 'Configure which actions require approval before being applied.',
                component: <ApprovalPolicies />,
                keywords: ['approval', 'policy', 'review', 'gate'],
            },
            {
                id: 'change-requests',
                title: 'Change requests',
                description: 'Review and approve pending change requests.',
                component: <ChangeRequestsList />,
                keywords: ['approval', 'review', 'pending', 'request'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-discussions',
        title: 'Discussions',
        settings: [
            {
                id: 'discussion-mention-integrations',
                title: 'Integrations',
                description: 'Configure how discussion mentions are delivered via integrations.',
                component: <DiscussionMentionNotifications />,
                keywords: ['mention', 'notification', 'comment', 'discussion'],
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
                description:
                    'Send notifications when selected actions are performed by users. Supports Slack, Microsoft Teams, and Discord.',
                docsUrl: 'https://posthog.com/docs/webhooks',
                component: <WebhookIntegration />,
                keywords: ['notification', 'alert', 'http', 'callback', 'slack', 'teams', 'discord'],
            },
            {
                id: 'integration-slack',
                title: 'Slack integration',
                description:
                    'Integrate with Slack to subscribe to insights or dashboards for regular reports to channels of your choice.',
                docsUrl: 'https://posthog.com/docs/webhooks/slack',
                component: <SlackIntegration />,
                keywords: ['slack', 'channel', 'notification', 'subscribe', 'report'],
            },
            {
                id: 'integration-github',
                title: 'GitHub integration',
                description: 'Connect GitHub to link issues and pull requests with PostHog insights.',
                docsUrl: 'https://posthog.com/docs/error-tracking/integrations',
                component: <GithubIntegration />,
                keywords: ['github', 'git', 'repository', 'issue', 'pr'],
            },
            {
                id: 'integration-linear',
                title: 'Linear integration',
                description: 'Connect Linear to create and link issues directly from PostHog.',
                docsUrl: 'https://posthog.com/docs/error-tracking/integrations',
                component: <LinearIntegration />,
                keywords: ['linear', 'issue', 'project management', 'task'],
            },
            {
                id: 'integration-other',
                title: 'Other integrations',
                description: 'Browse and manage additional third-party integrations.',
                component: <IntegrationsList omitKinds={['slack', 'github', 'linear']} />,
                keywords: ['integration', 'connect', 'third-party', 'app'],
            },
            {
                id: 'integration-ip-allowlist',
                title: 'Static IP addresses',
                description:
                    'PostHog Cloud uses static IP addresses for outbound traffic. Add these to your firewall allowlist if needed.',
                component: <IPAllowListInfo />,
                keywords: ['whitelist', 'firewall', 'allowlist', 'cidr', 'ip'],
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
                description: 'Move this project to a different organization.',
                component: <ProjectMove />,
                keywords: ['transfer', 'move', 'organization'],
            },
            {
                id: 'environment-delete',
                title: 'Delete environment',
                description: 'Permanently delete this environment and all its data. This action cannot be undone.',
                component: <TeamDangerZone />,
                keywords: ['delete', 'remove', 'destroy'],
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
                description: 'A human-friendly name for this project.',
                component: <ProjectDisplayName />,
                keywords: ['name', 'rename', 'label'],
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
                description: 'Move this project to a different organization.',
                component: <ProjectMove />,
                keywords: ['transfer', 'move', 'organization'],
            },
            {
                id: 'project-delete',
                title: 'Delete project',
                description: 'Permanently delete this project and all its environments. This action cannot be undone.',
                component: <ProjectDangerZone />,
                keywords: ['delete', 'remove', 'destroy'],
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
                title: 'Name & logo',
                description:
                    "Your organization's name and logo are shown across the PostHog interface. Click the avatar to upload a custom logo.",
                component: <OrganizationDisplayName />,
                keywords: ['name', 'rename', 'label', 'organization', 'logo', 'image', 'brand', 'icon', 'avatar'],
            },
            {
                id: 'organization-ai-consent',
                title: 'PostHog AI data analysis',
                description: (
                    // Note: Sync the copy below with AIConsentPopoverWrapper.tsx
                    <>
                        PostHog AI features, such as the PostHog AI chat, use{' '}
                        <Tooltip title={`As of ${dayjs().format('MMMM YYYY')}: Anthropic and OpenAI`}>
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
                keywords: ['llm', 'consent', 'opt-in', 'data sharing'],
                searchDescription:
                    'PostHog AI features use external AI services for data analysis. This can involve transfer of identifying user data.',
            },
            {
                id: 'organization-ip-anonymization-default',
                title: 'IP data capture default',
                description:
                    'When enabled, new projects will automatically have "Discard client IP data" turned on. This is recommended for GDPR compliance. Existing projects are not affected.',
                component: <OrgIPAnonymizationDefault />,
                keywords: ['ip', 'anonymize', 'gdpr', 'privacy', 'geolocation'],
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-members',
        title: 'Members',
        settings: [
            {
                id: 'banner',
                title: null,
                component: <MembersPlatformAddonAd />,
            },
            {
                id: 'invites',
                title: 'Pending invites',
                description: 'Manage pending invitations to join your organization.',
                component: <Invites />,
                keywords: ['invite', 'email', 'pending', 'join'],
            },
            {
                id: 'members',
                title: 'Organization members',
                description: 'View and manage current members of your organization and their roles.',
                component: <Members />,
                keywords: ['member', 'user', 'role', 'admin', 'owner'],
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
                description:
                    'Use roles to group your organization members and assign them permissions. Roles are used for access control across your organization.',
                docsUrl: 'https://posthog.com/docs/settings/access-control',
                component: <RolesAccessControls />,
                keywords: ['role', 'permission', 'rbac', 'access control'],
            },
            {
                id: 'organization-default-role',
                title: 'Default role for new members',
                description:
                    'Automatically assign a role to new members when they join the organization. New users will inherit all permissions from this role.',
                component: <DefaultRoleSelector />,
                keywords: ['default', 'role', 'new member', 'onboarding'],
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
                docsUrl: 'https://posthog.com/docs/settings/sso',
                component: <VerifiedDomains />,
                keywords: ['sso', 'saml', 'single sign-on', 'domain verification', 'enforce'],
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-security',
        title: 'Security',
        settings: [
            {
                id: 'organization-security',
                title: 'Security',
                description:
                    'Configure organization-wide security policies including public sharing, session timeouts, and password requirements.',
                component: <OrganizationSecuritySettings />,
                keywords: ['password', 'session', 'timeout', 'compliance', 'sharing', 'public'],
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-integrations',
        title: 'Integrations',
        settings: [
            {
                id: 'organization-integrations-list',
                title: 'Connected integrations',
                description: 'Manage integrations connected at the organization level.',
                component: <OrganizationIntegrations />,
                keywords: ['integration', 'connect', 'third-party', 'oauth'],
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
                docsUrl: 'https://posthog.com/docs/advanced/proxy',
                component: <ManagedReverseProxy />,
                keywords: ['custom domain', 'dns', 'cname', 'ad blocker', 'first party'],
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-notifications',
        title: 'Notifications',
        settings: [
            {
                id: 'email-members',
                title: 'Notification preferences',
                description: 'Configure which emails your organization members receive from PostHog.',
                component: <OrganizationEmailPreferences />,
                keywords: ['email', 'notification', 'digest', 'unsubscribe'],
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
    {
        level: 'organization',
        id: 'organization-danger-zone',
        title: 'Danger zone',
        settings: [
            {
                id: 'organization-delete',
                title: 'Delete organization',
                description:
                    'Permanently delete your organization and all its projects and data. This action cannot be undone.',
                component: <OrganizationDangerZone />,
                keywords: ['delete', 'remove', 'destroy'],
            },
        ],
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
                keywords: ['name', 'email', 'profile', 'personal'],
            },
            {
                id: 'change-password',
                title: <ChangePasswordTitle />,
                component: <ChangePassword />,
                keywords: ['password', 'security', 'credential'],
            },
            {
                id: '2fa',
                title: 'Two-factor authentication',
                description: 'Add an extra layer of security to your account using an authenticator app or passkeys.',
                component: <TwoFactorSettings />,
                keywords: ['two-factor', 'mfa', 'authenticator', 'security', 'totp'],
            },
            {
                id: 'passkeys',
                title: 'Passkeys',
                description: 'Manage your passkeys for passwordless sign-in and two-factor authentication.',
                component: <PasskeySettings />,
                keywords: ['webauthn', 'fido', 'biometric', 'passwordless'],
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
                description: 'Choose which email notifications you receive from PostHog.',
                component: <UpdateEmailPreferences />,
                keywords: ['email', 'notification', 'digest', 'unsubscribe'],
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
                keywords: ['dark mode', 'light mode', 'appearance', 'color scheme'],
            },
            {
                id: 'sql-editor-tab-preference',
                title: 'SQL editor new tab behavior',
                description: 'Configure whether new SQL queries open in new tabs or reuse existing ones.',
                component: <SqlEditorTabPreference />,
                keywords: ['sql', 'editor', 'tab', 'query'],
            },
            {
                id: 'optout',
                title: 'Anonymize data collection',
                description:
                    'PostHog uses PostHog to capture information about how people use the product. Anonymize your usage data if you prefer not to share it.',
                component: <OptOutCapture />,
                hideOn: [Realm.Cloud],
                keywords: ['telemetry', 'opt out', 'privacy', 'tracking'],
            },
            {
                id: 'allow-impersonation',
                title: 'Support access',
                component: <AllowImpersonation />,
                flag: 'CONTROL_SUPPORT_LOGIN',
                keywords: ['impersonation', 'support login', 'debug'],
            },
            {
                id: 'hedgehog-mode',
                title: 'Hedgehog mode',
                description: 'Enable the PostHog hedgehog companion that follows you around the app.',
                component: <HedgehogModeSettings />,
                keywords: ['hedgehog', 'mascot', 'fun', 'companion', 'hog'],
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
        id: 'user-feature-previews',
        title: 'Feature previews',
        settings: [
            {
                id: 'feature-previews',
                title: 'Feature previews',
                description:
                    'Try out upcoming PostHog features before they are generally available. Toggling a preview enables it for your account only.',
                component: <FeaturePreviewsSettings />,
                keywords: ['beta', 'early access', 'preview', 'opt-in'],
            },
            {
                id: 'feature-previews-coming-soon',
                title: 'Coming soon',
                description: 'Get notified when upcoming features are ready for preview.',
                component: <FeaturePreviewsComingSoon />,
                keywords: ['upcoming', 'notify', 'concept', 'future'],
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
                description:
                    'These keys allow full access to your personal account through the API. Only give keys the permissions they need, and delete unused keys promptly.',
                docsUrl: 'https://posthog.com/docs/api',
                component: <PersonalAPIKeys />,
                keywords: ['token', 'api key', 'authentication', 'secret'],
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
                description: 'Permanently delete your PostHog account. This action cannot be undone.',
                component: <UserDangerZone />,
                keywords: ['delete', 'remove', 'account'],
            },
        ],
    },
]
