import { PersonsOnEvents } from 'scenes/settings/project/PersonsOnEvents'

import { Invites } from './organization/Invites'
import { Members } from './organization/Members'
import { OrganizationDangerZone } from './organization/OrganizationDangerZone'
import { OrganizationDisplayName } from './organization/OrgDisplayName'
import { OrganizationEmailPreferences } from './organization/OrgEmailPreferences'
import { PermissionsGrid } from './organization/Permissions/PermissionsGrid'
import { VerifiedDomains } from './organization/VerifiedDomains/VerifiedDomains'
import { AutocaptureSettings, ExceptionAutocaptureSettings } from './project/AutocaptureSettings'
import { CorrelationConfig } from './project/CorrelationConfig'
import { DataAttributes } from './project/DataAttributes'
import { GroupAnalyticsConfig } from './project/GroupAnalyticsConfig'
import { HeatmapsSettings } from './project/HeatmapsSettings'
import { IPAllowListInfo } from './project/IPAllowListInfo'
import { IPCapture } from './project/IPCapture'
import { PathCleaningFiltersConfig } from './project/PathCleaningFiltersConfig'
import { PersonDisplayNameProperties } from './project/PersonDisplayNameProperties'
import { ProjectAccessControl } from './project/ProjectAccessControl'
import { ProjectDangerZone } from './project/ProjectDangerZone'
import {
    Bookmarklet,
    ProjectDisplayName,
    ProjectTimezone,
    ProjectToolbarURLs,
    ProjectVariables,
    WebSnippet,
} from './project/ProjectSettings'
import { Proxy } from './project/Proxy'
import {
    NetworkCaptureSettings,
    ReplayAISettings,
    ReplayAuthorizedDomains,
    ReplayCostControl,
    ReplayGeneral,
} from './project/SessionRecordingSettings'
import { SlackIntegration } from './project/SlackIntegration'
import { SurveySettings } from './project/SurveySettings'
import { ProjectAccountFiltersSetting } from './project/TestAccountFiltersConfig'
import { WebhookIntegration } from './project/WebhookIntegration'
import { SettingSection } from './types'
import { ChangePassword } from './user/ChangePassword'
import { OptOutCapture } from './user/OptOutCapture'
import { PersonalAPIKeys } from './user/PersonalAPIKeys'
import { ThemeSwitcher } from './user/ThemeSwitcher'
import { TwoFactorAuthentication } from './user/TwoFactorAuthentication'
import { UpdateEmailPreferences } from './user/UpdateEmailPreferences'
import { UserDetails } from './user/UserDetails'

export const SettingsMap: SettingSection[] = [
    // PROJECT
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
                component: <ProjectVariables />,
            },
        ],
    },
    {
        level: 'project',
        id: 'project-autocapture',
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
                id: 'autocapture-data-attributes',
                title: 'Data attributes',
                component: <DataAttributes />,
            },
        ],
    },

    {
        level: 'project',
        id: 'project-product-analytics',
        title: 'Product analytics',
        settings: [
            {
                id: 'date-and-time',
                title: 'Date & time',
                component: <ProjectTimezone />,
            },
            {
                id: 'internal-user-filtering',
                title: 'Filter out internal and test users',
                component: <ProjectAccountFiltersSetting />,
            },
            {
                id: 'persons-on-events',
                title: 'Event person filtering behavior',
                component: <PersonsOnEvents />,
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
        ],
    },

    {
        level: 'project',
        id: 'project-replay',
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
        level: 'project',
        id: 'project-surveys',
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
        level: 'project',
        id: 'project-toolbar',
        title: 'Toolbar',
        settings: [
            {
                id: 'authorized-toolbar-urls',
                title: 'Authorized toolbar URLs',
                component: <ProjectToolbarURLs />,
            },
        ],
    },
    {
        level: 'project',
        id: 'project-integrations',
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
                id: 'integration-ip-allowlist',
                title: 'Static IP addresses',
                component: <IPAllowListInfo />,
            },
        ],
    },
    {
        level: 'project',
        id: 'project-rbac',
        title: 'Access control',
        settings: [
            {
                id: 'project-rbac',
                title: 'Access control',
                component: <ProjectAccessControl />,
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
        title: 'Proxy',
        flag: 'PROXY_AS_A_SERVICE',
        settings: [
            {
                id: 'organization-proxy',
                title: 'Proxy',
                component: <Proxy />,
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
        ],
    },
]
