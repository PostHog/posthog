import { BounceRatePageViewModeSetting } from 'scenes/settings/environment/BounceRatePageViewMode'
import { PersonsJoinMode } from 'scenes/settings/environment/PersonsJoinMode'
import { PersonsOnEvents } from 'scenes/settings/environment/PersonsOnEvents'
import { SessionsTableVersion } from 'scenes/settings/environment/SessionsTableVersion'

import {
    AutocaptureSettings,
    ExceptionAutocaptureSettings,
    WebVitalsAutocaptureSettings,
} from './environment/AutocaptureSettings'
import { CorrelationConfig } from './environment/CorrelationConfig'
import { DataAttributes } from './environment/DataAttributes'
import { GroupAnalyticsConfig } from './environment/GroupAnalyticsConfig'
import { HeatmapsSettings } from './environment/HeatmapsSettings'
import { IPAllowListInfo } from './environment/IPAllowListInfo'
import { IPCapture } from './environment/IPCapture'
import { ManagedReverseProxy } from './environment/ManagedReverseProxy'
import { OtherIntegrations } from './environment/OtherIntegrations'
import { PathCleaningFiltersConfig } from './environment/PathCleaningFiltersConfig'
import { PersonDisplayNameProperties } from './environment/PersonDisplayNameProperties'
import {
    NetworkCaptureSettings,
    ReplayAISettings,
    ReplayAuthorizedDomains,
    ReplayCostControl,
    ReplayGeneral,
} from './environment/SessionRecordingSettings'
import { SlackIntegration } from './environment/SlackIntegration'
import { SurveySettings } from './environment/SurveySettings'
import { TeamAccessControl } from './environment/TeamAccessControl'
import { TeamDangerZone } from './environment/TeamDangerZone'
import {
    Bookmarklet,
    TeamDisplayName,
    TeamTimezone,
    TeamToolbarURLs,
    TeamVariables,
    WebSnippet,
} from './environment/TeamSettings'
import { ProjectAccountFiltersSetting } from './environment/TestAccountFiltersConfig'
import { WebhookIntegration } from './environment/WebhookIntegration'
import { Invites } from './organization/Invites'
import { Members } from './organization/Members'
import { OrganizationDangerZone } from './organization/OrganizationDangerZone'
import { OrganizationDisplayName } from './organization/OrgDisplayName'
import { OrganizationEmailPreferences } from './organization/OrgEmailPreferences'
import { OrganizationLogo } from './organization/OrgLogo'
import { PermissionsGrid } from './organization/Permissions/PermissionsGrid'
import { VerifiedDomains } from './organization/VerifiedDomains/VerifiedDomains'
import { ProjectDangerZone } from './project/ProjectDangerZone'
import { ProjectDisplayName } from './project/ProjectSettings'
import { SettingSection } from './types'
import { ChangePassword } from './user/ChangePassword'
import { HedgehogModeSettings } from './user/HedgehogModeSettings'
import { OptOutCapture } from './user/OptOutCapture'
import { PersonalAPIKeys } from './user/PersonalAPIKeys'
import { ThemeSwitcher } from './user/ThemeSwitcher'
import { TwoFactorAuthentication } from './user/TwoFactorAuthentication'
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
                id: 'heatmaps',
                title: 'Heatmaps',
                component: <HeatmapsSettings />,
            },
            {
                id: 'exception-autocapture',
                title: 'Exception autocapture',
                component: <ExceptionAutocaptureSettings />,
                flag: 'EXCEPTION_AUTOCAPTURE',
            },
            {
                id: 'web-vitals-autocapture',
                title: 'Web vitals autocapture',
                component: <WebVitalsAutocaptureSettings />,
            },
            {
                id: 'autocapture-data-attributes',
                title: 'Data attributes',
                component: <DataAttributes />,
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
                id: 'bounce-rate-page-view-mode',
                title: 'Bounce rate page view mode',
                component: <BounceRatePageViewModeSetting />,
                flag: 'SETTINGS_BOUNCE_RATE_PAGE_VIEW_MODE',
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
                id: 'replay-authorized-domains',
                title: 'Authorized domains for replay',
                component: <ReplayAuthorizedDomains />,
            },
            {
                id: 'replay-ingestion',
                title: 'Ingestion controls',
                component: <ReplayCostControl />,
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
        id: 'environment-toolbar',
        title: 'Toolbar',
        settings: [
            {
                id: 'authorized-toolbar-urls',
                title: 'Authorized toolbar URLs',
                component: <TeamToolbarURLs />,
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
        id: 'environment-rbac',
        title: 'Access control',
        settings: [
            {
                id: 'environment-rbac',
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
        id: 'organization-rbac',
        title: 'Role-based access',
        settings: [
            {
                id: 'organization-rbac',
                title: 'Role-based access',
                component: <PermissionsGrid />,
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
                component: <TwoFactorAuthentication />,
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
            },
            {
                id: 'hedgehog-mode',
                title: 'Hedgehog mode',
                component: <HedgehogModeSettings />,
            },
        ],
    },
]
