import type { Meta, StoryFn } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { DevLoginPanel } from './DevLoginPanel'

type StoryArgs = {
    allowDevLogin: boolean
    devUsers: 'none' | 'default' | 'many'
}

const DEV_USERS_MOCKS = {
    none: { users: [] },
    default: {
        users: [
            {
                email: 'test@posthog.com',
                is_staff: true,
                label: 'Default test user',
            },
            { email: 'staff@posthog.com', is_staff: true, label: null },
        ],
    },
    many: {
        users: [
            {
                email: 'test@posthog.com',
                is_staff: true,
                label: 'Default test user',
            },
            { email: 'staff@posthog.com', is_staff: true, label: null },
            { email: 'admin@posthog.com', is_staff: true, label: 'Admin' },
            { email: 'user@posthog.com', is_staff: false, label: null },
            {
                email: 'long-email-address-that-truncates@posthog.com',
                is_staff: false,
                label: 'New',
            },
        ],
    },
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
            '/api/login/dev': DEV_USERS_MOCKS[devUsers],
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
