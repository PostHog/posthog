import { AvailableFeature } from '~/types'

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
import {
    ReplayAuthorizedDomains,
    ReplayCostControl,
    ReplayGeneral,
    ReplaySummarySettings,
} from './project/SessionRecordingSettings'
import { SettingPersonsOnEvents } from './project/SettingPersonsOnEvents'
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
        title: 'Autocapture',

        settings: [
            {
                id: 'autocapture',
                title: 'Autocapture',
                component: <AutocaptureSettings />,
            },
            {
                id: 'exception-autocapture',
                title: 'Exception Autocapture',
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
        title: 'Product Analytics',
        settings: [
            {
                id: 'date-and-time',
                title: 'Date & Time',
                component: <ProjectTimezone />,
            },
            {
                id: 'internal-user-filtering',
                title: 'Filter out internal and test users',
                component: <ProjectAccountFiltersSetting />,
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
                title: 'IP Data capture configuration',
                component: <IPCapture />,
            },
            {
                id: 'group-analytics',
                title: 'Group Analytics',
                component: <GroupAnalyticsConfig />,
            },
            {
                id: 'persons-on-events',
                title: 'Persons on events (beta)',
                component: <SettingPersonsOnEvents />,
            },
        ],
    },

    {
        level: 'project',
        id: 'project-replay',
        title: 'Session Replay',
        settings: [
            {
                id: 'replay',
                title: 'Session Replay',
                component: <ReplayGeneral />,
            },
            {
                id: 'replay-authorized-domains',
                title: 'Authorized Domains for Replay',
                component: <ReplayAuthorizedDomains />,
            },
            {
                id: 'replay-ingestion',
                title: 'Ingestion controls',
                component: <ReplayCostControl />,
                flag: 'SESSION_RECORDING_SAMPLING',
                features: [
                    AvailableFeature.SESSION_REPLAY_SAMPLING,
                    AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING,
                    AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM,
                ],
            },
            {
                id: 'replay-ai-config',
                title: 'AI Recording Summary',
                component: <ReplaySummarySettings />,
                flag: 'AI_SESSION_SUMMARY',
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
                title: 'Authorized Toolbar URLs',
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
        ],
    },
    {
        level: 'project',
        id: 'project-rbac',
        title: 'Access control',
        settings: [
            {
                id: 'project-rbac',
                title: 'Access Control',
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
                title: 'Pending Invites',
                component: <Invites />,
            },
            {
                id: 'members',
                title: 'Members',
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
        title: 'Authentication Domains & SSO',
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
        flag: 'ROLE_BASED_ACCESS',
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
        title: 'Personal API Keys',
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
                title: 'Anonymize Data Collection',
                component: <OptOutCapture />,
            },
        ],
    },
]
