import { OrganizationMembershipLevel } from 'lib/constants'
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

export type SettingLevel = 'user' | 'project' | 'organization'
export type SettingSectionId =
    | 'user-details'
    | 'user-api-keys'
    | 'user-notifications'
    | 'organization-details'
    | 'organization-members'
    | 'organization-authentication'

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
    minimumAccessLevel?: EitherMembershipLevel
}

{
    /* <div className="border rounded p-6">
                    <LemonDivider className="my-6" />
                    <RestrictedArea
                        Component={EmailPreferences}
                        minimumAccessLevel={OrganizationMembershipLevel.Admin}
                    />
                    <LemonDivider className="my-6" />
                    <RestrictedArea Component={DangerZone} minimumAccessLevel={OrganizationMembershipLevel.Owner} />
                </div> */
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
