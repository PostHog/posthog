import { ChangePassword } from './user/ChangePassword'
import { OptOutCapture } from './user/OptOutCapture'
import { PersonalAPIKeys } from './user/PersonalAPIKeys'
import { TwoFactorAuthentication } from './user/TwoFactorAuthentication'
import { UpdateEmailPreferences } from './user/UpdateEmailPreferences'
import { UserDetails } from './user/UserDetails'

export type Setting = {
    id: string
    title: string
    description?: JSX.Element | string
    component: JSX.Element
}

export type SettingSection = {
    id: string
    title: string
    settings: Setting[]
}

const UserSettings: Setting[] = [
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
        id: 'personal-api-keys',
        title: 'Personal API keys',
        component: <PersonalAPIKeys />,
    },
    {
        id: 'two-factor-authentication',
        title: 'Two-factor authentication',
        component: <TwoFactorAuthentication />,
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
]

export const AllSettings: SettingSection[] = [
    {
        id: 'user',
        title: 'User',
        settings: UserSettings,
    },
]
