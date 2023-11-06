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

export type SettingLevel = 'user' | 'project' | 'organization'
export type SettingSectionId =
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
    {
        level: 'organization',
        id: 'organization-details',
        title: 'Details',
        settings: [
            {
                id: 'organization-details',
                title: 'Details',
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
        level: 'user',
        id: 'user-details',
        title: 'Details',
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
