import { ChangePassword } from './user/ChangePassword'
import { OptOutCapture } from './user/OptOutCapture'
import { PersonalAPIKeys } from './user/PersonalAPIKeys'
import { TwoFactorAuthentication } from './user/TwoFactorAuthentication'
import { UpdateEmailPreferences } from './user/UpdateEmailPreferences'
import { UserDetails } from './user/UserDetails'
import { EitherMembershipLevel } from 'lib/utils/permissioning'
import { OrganizationDisplayName } from './organization/OrgDisplayName'
import { Invites } from './organization/Invites'
import { Members } from './organization/Members'
import { VerifiedDomains } from './organization/VerifiedDomains/VerifiedDomains'
import { OrganizationEmailPreferences } from './organization/OrgEmailPreferences'
import { DangerZone } from './organization/DangerZone'
import { PermissionsGrid } from './organization/Permissions/PermissionsGrid'
import { FEATURE_FLAGS } from 'lib/constants'
import {
    Bookmarklet,
    ProjectDisplayName,
    ProjectTimezone,
    ProjectToolbarURLs,
    ProjectVariables,
    WebSnippet,
} from './project/ProjectSettings'
import { AutocaptureSettings, ExceptionAutocaptureSettings } from './project/AutocaptureSettings'
import { DataAttributes } from './project/DataAttributes'
import { ReplayAuthorizedDomains, ReplayCostControl, ReplayGeneral } from './project/SessionRecordingSettings'
import { ProjectDangerZone } from './project/ProjectDangerZone'
import { ProjectAccessControl } from './project/ProjectAccessControl'
import { ProjectAccountFiltersSetting } from './project/TestAccountFiltersConfig'
import { CorrelationConfig } from './project/CorrelationConfig'
import { PersonDisplayNameProperties } from './project/PersonDisplayNameProperties'
import { IPCapture } from './project/IPCapture'
import { WebhookIntegration } from './project/WebhookIntegration'
import { SlackIntegration } from './project/SlackIntegration'
import { PathCleaningFiltersConfig } from './project/PathCleaningFiltersConfig'
import { GroupAnalyticsConfig } from './project/GroupAnalyticsConfig'
import { SurveySettings } from './project/SurveySettings'
import { SettingPersonsOnEvents } from './project/SettingPersonsOnEvents'

export type SettingLevel = 'user' | 'project' | 'organization'
export type SettingSectionId =
    | 'project-details'
    | 'project-autocapture'
    | 'project-replay'
    | 'user-details'
    | 'user-api-keys'
    | 'user-notifications'
    | 'organization-details'
    | 'organization-members'
    | 'organization-authentication'
    | 'organization-danger-zone'
    | 'organization-rbac'

export const SettingLevels: SettingLevel[] = ['project', 'organization', 'user']

export type Setting = {
    id: string
    title: string
    description?: JSX.Element | string
    component: JSX.Element
}

export type SettingSection = {
    id: SettingSectionId
    title: string
    level: SettingLevel
    settings: Setting[]
    flag?: keyof typeof FEATURE_FLAGS
    minimumAccessLevel?: EitherMembershipLevel
}

export const SettingsSections: SettingSection[] = [
    // PROJECT
    {
        level: 'project',
        id: 'project-details',
        title: 'General',
        settings: [
            {
                id: 'project-display-name',
                title: 'Display name',
                component: <ProjectDisplayName />,
            },
            {
                id: 'project-snippet',
                title: 'Web snippet',
                component: <WebSnippet />,
            },
            {
                id: 'project-bookmarklet',
                title: 'Bookmarklet',
                component: <Bookmarklet />,
            },
            {
                id: 'project-variables',
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
                id: 'project-autocapture',
                title: 'Autocapture',
                component: <AutocaptureSettings />,
            },
            {
                id: 'project-exception-autocapture',
                title: 'Exception Autocapture',
                component: <ExceptionAutocaptureSettings />,
            },
            {
                id: 'project-autocapture-data-attributes',
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
                id: 'project-date-and-time',
                title: 'Date & Time',
                component: <ProjectTimezone />,
            },
            {
                id: 'project-internal-user-filtering',
                title: 'Filter our internal and test users',
                component: <ProjectAccountFiltersSetting />,
            },
            {
                id: 'project-correlation-analysis',
                title: 'Correlation analysis exclusions',
                component: <CorrelationConfig />,
            },
            {
                id: 'project-person-display-name',
                title: 'Person display name',
                component: <PersonDisplayNameProperties />,
            },
            {
                id: 'project-path-cleaning',
                title: 'Path cleaning rules',
                component: <PathCleaningFiltersConfig />,
            },
            {
                id: 'project-datacapture',
                title: 'IP Data capture configuration',
                component: <IPCapture />,
            },
            {
                id: 'project-group-analytics',
                title: 'Group Analytics',
                component: <GroupAnalyticsConfig />,
            },
            {
                id: 'project-persons-on-events',
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
                id: 'project-replay-general',
                title: 'Session Replay',
                component: <ReplayGeneral />,
            },
            {
                id: 'project-replay-authorized-domains',
                title: 'Authorized Domains for Replay',
                component: <ReplayAuthorizedDomains />,
            },
            {
                id: 'project-replay-ingestion',
                title: 'Ingestion controls',
                component: <ReplayCostControl />,
            },
        ],
    },
    {
        level: 'project',
        id: 'project-surveys',
        title: 'Surveys',
        settings: [
            {
                id: 'project-surveys-interface',
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
                id: 'project-authorized-toolbar-urls',
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
                id: 'project-integration-webhooks',
                title: 'Webhook integration',
                component: <WebhookIntegration />,
            },
            {
                id: 'project-integration-slack',
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
                id: 'organization-details',
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
                id: 'organization-invites',
                title: 'Pending Invites',
                component: <Invites />,
            },
            {
                id: 'organization-members',
                title: 'Members',
                component: <Members />,
            },
            {
                id: 'organization-email-members',
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
                id: 'organization-domains',
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
                component: <DangerZone />,
            },
        ],
    },

    // USER
    {
        level: 'user',
        id: 'user-details',
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
                id: 'two-factor-authentication',
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
        id: 'user-notifications',
        title: 'Notifications',
        settings: [
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
