import { ChangePassword } from './user/ChangePassword'
import { OptOutCapture } from './user/OptOutCapture'
import { PersonalAPIKeys } from './user/PersonalAPIKeys'
import { TwoFactorAuthentication } from './user/TwoFactorAuthentication'
import { UpdateEmailPreferences } from './user/UpdateEmailPreferences'
import { UserDetails } from './user/UserDetails'

export type SettingLevel = 'user' | 'project' | 'organization'
export type SettingSectionId = 'user-details' | 'user-api-keys' | 'user-notifications'

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
}

export const SettingsSections: SettingSection[] = [
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
