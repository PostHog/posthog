import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { dayjs } from 'lib/dayjs'
import { ErrorTrackingAlerting } from 'scenes/error-tracking/configuration/alerting/ErrorTrackingAlerting'
import { ErrorTrackingSymbolSets } from 'scenes/error-tracking/configuration/symbol-sets/ErrorTrackingSymbolSets'
import { organizationLogic } from 'scenes/organizationLogic'
import { BounceRateDurationSetting } from 'scenes/settings/environment/BounceRateDuration'
import { BounceRatePageViewModeSetting } from 'scenes/settings/environment/BounceRatePageViewMode'
import { CookielessServerHashModeSetting } from 'scenes/settings/environment/CookielessServerHashMode'
import { CustomChannelTypes } from 'scenes/settings/environment/CustomChannelTypes'
import { DeadClicksAutocaptureSettings } from 'scenes/settings/environment/DeadClicksAutocaptureSettings'
import { MaxMemorySettings } from 'scenes/settings/environment/MaxMemorySettings'
import { PersonsJoinMode } from 'scenes/settings/environment/PersonsJoinMode'
import { PersonsOnEvents } from 'scenes/settings/environment/PersonsOnEvents'
import { ReplayTriggers } from 'scenes/settings/environment/ReplayTriggers'
import { SessionsTableVersion } from 'scenes/settings/environment/SessionsTableVersion'
import { SessionsV2JoinModeSettings } from 'scenes/settings/environment/SessionsV2JoinModeSettings'
import { urls } from 'scenes/urls'

import { Realm } from '~/types'

import {
    AutocaptureSettings,
    ExceptionAutocaptureSettings,
    WebVitalsAutocaptureSettings,
} from './environment/AutocaptureSettings'
import { CorrelationConfig } from './environment/CorrelationConfig'
import { DataAttributes } from './environment/DataAttributes'
import { DataColorThemes } from './environment/DataColorThemes'
import { ErrorTrackingIntegrations } from './environment/ErrorTrackingIntegrations'
import { FeatureFlagSettings } from './environment/FeatureFlagSettings'
import { GroupAnalyticsConfig } from './environment/GroupAnalyticsConfig'
import { HeatmapsSettings } from './environment/HeatmapsSettings'
import { HumanFriendlyComparisonPeriodsSetting } from './environment/HumanFriendlyComparisonPeriodsSetting'
import { IPAllowListInfo } from './environment/IPAllowListInfo'
import { IPCapture } from './environment/IPCapture'
import { ManagedReverseProxy } from './environment/ManagedReverseProxy'
import { OtherIntegrations } from './environment/OtherIntegrations'
import { PathCleaningFiltersConfig } from './environment/PathCleaningFiltersConfig'
import { PersonDisplayNameProperties } from './environment/PersonDisplayNameProperties'
import { RevenueBaseCurrencySettings } from './environment/RevenueBaseCurrencySettings'
import {
    NetworkCaptureSettings,
    ReplayAISettings,
    ReplayAuthorizedDomains,
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
import { UserGroups } from './environment/UserGroups'
import { WebhookIntegration } from './environment/WebhookIntegration'
import { Invites } from './organization/Invites'
import { Members } from './organization/Members'
import { OrganizationAI } from './organization/OrgAI'
import { OrganizationDangerZone } from './organization/OrganizationDangerZone'
import { OrganizationDisplayName } from './organization/OrgDisplayName'
import { OrganizationEmailPreferences } from './organization/OrgEmailPreferences'
import { OrganizationLogo } from './organization/OrgLogo'
import { RoleBasedAccess } from './organization/Permissions/RoleBasedAccess'
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
        id: 'environment-product-analytics',
        title: 'Product analytics',
        settings: [
            {
                id: 'date-and-time',
                title: 'Date & time',
                component: <TeamTimezone />,
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
                flag: 'INSIGHT_COLORS',
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
                id: 'revenue-base-currency',
                title: 'Revenue base currency',
                component: <RevenueBaseCurrencySettings />,
                flag: 'WEB_REVENUE_TRACKING',
            },
            {
                id: 'cookieless-server-hash-mode',
                title: 'Cookieless server hash mode',
                component: <CookielessServerHashModeSetting />,
                flag: 'COOKIELESS_SERVER_HASH_MODE_SETTING',
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
                id: 'replay-network',
                title: 'Network capture',
                component: <NetworkCaptureSettings />,
            },
            {
                id: 'replay-masking',
                title: 'Masking',
                component: <ReplayMaskingSettings />,
            },
            {
                id: 'replay-authorized-domains',
                title: 'Authorized domains for replay',
                component: <ReplayAuthorizedDomains />,
                allowForTeam: (t) => !!t?.recording_domains?.length,
            },
            {
                id: 'replay-triggers',
                title: 'Replay triggers',
                component: <ReplayTriggers />,
            },
            {
                id: 'replay-ai-config',
                title: 'AI recording summary',
                component: <ReplayAISettings />,
                flag: 'AI_SESSION_PERMISSIONS',
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
                id: 'error-tracking-user-groups',
                title: 'User groups',
                description: 'Allow collections of users to be assigned to issues',
                component: <UserGroups />,
            },
            {
                id: 'error-tracking-integrations',
                title: 'Integrations',
                component: <ErrorTrackingIntegrations />,
                flag: 'ERROR_TRACKING_INTEGRATIONS',
            },
            {
                id: 'error-tracking-symbol-sets',
                title: 'Symbol sets',
                component: <ErrorTrackingSymbolSets />,
            },
            {
                id: 'error-tracking-alerting',
                title: 'Alerting',
                component: <ErrorTrackingAlerting />,
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-max',
        title: 'Max AI',
        flag: 'ARTIFICIAL_HOG',
        settings: [
            {
                id: 'core-memory',
                title: 'Memory',
                description:
                    "Max automatically remembers details about your company and product. This context helps our AI assistant provide relevant answers and suggestions. If there are any details you don't want Max to remember, you can edit or remove them below.",
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
                id: 'integration-error-tracking',
                title: 'Error tracking integrations',
                component: <ErrorTrackingIntegrations />,
                flag: 'ERROR_TRACKING_INTEGRATIONS',
            },
            {
                id: 'integration-other',
                title: 'Other integrations',
                component: <OtherIntegrations />,
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
                        <Tooltip
                            title={`As of ${dayjs().format(
                                'MMMM YYYY'
                            )}: OpenAI for core analysis, Perplexity for fetching product information`}
                        >
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
                component: <RoleBasedAccess />,
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
        id: 'user-customization',
        title: 'Customization',
        settings: [
            {
                id: 'theme',
                title: 'Theme',
                component: <ThemeSwitcher onlyLabel />,
            },
            {
                id: 'notifications',
                title: 'Notifications',
                component: <UpdateEmailPreferences />,
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
]
