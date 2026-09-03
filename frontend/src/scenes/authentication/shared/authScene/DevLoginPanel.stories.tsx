import type { Meta, StoryFn } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import type { DevUser } from '../devLoginLogic'
import { DevLoginPanel } from './DevLoginPanel'

type StoryArgs = {
    allowDevLogin: boolean
    devUsers: 'none' | 'default' | 'many'
}

const DEV_USERS_MOCKS: Record<StoryArgs['devUsers'], DevUser[]> = {
    none: [],
    default: [
        {
            email: 'test@posthog.com',
            first_name: 'Test',
            is_staff: true,
            label: 'Default test user',
            last_login: '2026-07-31T09:00:00Z',
        },
        { email: 'staff@posthog.com', first_name: 'Staff', is_staff: true, label: null, last_login: null },
        {
            email: 'long-email-address-that-truncates@posthog.com',
            first_name: 'Longwinded',
            is_staff: false,
            label: null,
            last_login: null,
        },
    ],
    // The growth team's local instances look like this: hundreds of throwaway signup test accounts.
    many: [
        {
            email: 'test@posthog.com',
            first_name: 'Test',
            is_staff: true,
            label: 'Default test user',
            last_login: '2026-07-31T09:00:00Z',
        },
        ...Array.from({ length: 320 }, (_, index): DevUser => {
            const firstName = ['Ada', 'Byron', 'Cleo', 'Dorian', 'Edith', 'Felix', 'Greta'][index % 7]
            return {
                email: `${firstName.toLowerCase()}-${String(index).padStart(4, '0')}@posthog.dev`,
                first_name: firstName,
                is_staff: false,
                label: null,
                last_login: index < 5 ? `2026-07-3${index}T09:00:00Z` : null,
            }
        }),
    ],
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Authentication/DevLoginPanel',
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    argTypes: {
        allowDevLogin: { control: 'boolean', name: 'Allow dev login' },
        devUsers: {
            control: 'select',
            options: ['none', 'default', 'many'],
            name: 'Dev users',
        },
    },
    args: {
        allowDevLogin: true,
        devUsers: 'default',
    },
}
export default meta

const Template: StoryFn<StoryArgs> = ({ allowDevLogin, devUsers }) => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                is_debug: true,
                allow_dev_login: allowDevLogin,
            },
            '/api/login/dev': { users: DEV_USERS_MOCKS[devUsers] },
        },
    })

    return (
        <div className="min-h-screen bg-[#eef0e7]">
            <DevLoginPanel />
        </div>
    )
}

export const Default: StoryFn<StoryArgs> = Template.bind({})

export const ManyUsers: StoryFn<StoryArgs> = Template.bind({})
ManyUsers.args = { devUsers: 'many' }

export const NoDevLogin: StoryFn<StoryArgs> = Template.bind({})
NoDevLogin.args = { allowDevLogin: false, devUsers: 'none' }
