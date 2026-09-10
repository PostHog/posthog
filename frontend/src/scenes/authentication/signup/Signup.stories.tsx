import type { Meta, StoryFn } from '@storybook/react'
import { HttpResponse, delay } from 'msw'
import { useEffect } from 'react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { PENDING_OAUTH_CONNECTION_COOKIE } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { Signup } from './Signup'
import { signupLogic } from './signupForm/signupLogic'

type PanelOption = '1: Email' | '2: Password' | '3: Profile'

const PANEL_INDEX: Record<PanelOption, 0 | 1 | 2> = {
    '1: Email': 0,
    '2: Password': 1,
    '3: Profile': 2,
}

type StoryArgs = {
    cloud: boolean
    region: 'US' | 'EU'
    googleOAuth: boolean
    github: boolean
    gitlab: boolean
    panel: PanelOption
    pendingOAuthConnection: boolean
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Signup',
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: { '/api/users/@me': () => [500, null] },
            post: {
                '/api/signup': async () => {
                    await delay(1000)
                    return HttpResponse.json({ success: true })
                },
            },
        }),
    ],
    argTypes: {
        cloud: { control: 'boolean', name: 'Cloud' },
        region: { control: 'select', options: ['US', 'EU'], name: 'Region', if: { arg: 'cloud' } },
        googleOAuth: { control: 'boolean', name: 'Google OAuth' },
        github: { control: 'boolean', name: 'GitHub' },
        gitlab: { control: 'boolean', name: 'GitLab' },
        panel: {
            control: 'select',
            name: 'Step',
            options: ['1: Email', '2: Password', '3: Profile'] satisfies PanelOption[],
        },
        pendingOAuthConnection: { control: 'boolean', name: 'Pending OAuth connection' },
    },
    args: {
        cloud: true,
        region: 'US',
        googleOAuth: true,
        github: true,
        gitlab: true,
        panel: '1: Email',
        pendingOAuthConnection: false,
    },
}
export default meta

const PENDING_CONNECTION_COOKIE_VALUE = encodeURIComponent(
    JSON.stringify({
        client_name: 'Claude',
        client_id: 'https://claude.ai/.well-known/oauth-client',
        redirect_host: 'claude.ai',
        region: 'US',
    })
)

// Set synchronously: the scene reads the cookie while it mounts during this same render.
function setPendingOAuthConnectionCookie(pending: boolean): void {
    document.cookie = pending
        ? `${PENDING_OAUTH_CONNECTION_COOKIE}=${PENDING_CONNECTION_COOKIE_VALUE}; path=/`
        : `${PENDING_OAUTH_CONNECTION_COOKIE}=; max-age=0; path=/`
}

const Template: StoryFn<StoryArgs> = ({
    cloud,
    region,
    googleOAuth,
    github,
    gitlab,
    panel: panelOption,
    pendingOAuthConnection,
}) => {
    const panel = PANEL_INDEX[panelOption]
    setPendingOAuthConnectionCookie(pendingOAuthConnection)
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud,
                region: cloud ? region : undefined,
                realm: cloud ? 'cloud' : 'hosted-clickhouse',
                is_debug: cloud,
                can_create_org: cloud,
                available_social_auth_providers: {
                    'google-oauth2': googleOAuth,
                    github,
                    gitlab,
                    saml: false,
                },
            },
        },
    })

    useDelayedOnMountEffect(() => userLogic.actions.loadUserSuccess(null))

    useEffect(() => {
        signupLogic.actions.setPanel(panel)
        if (panel > 0) {
            signupLogic.actions.setSignupPanelEmailValue('email', 'test@posthog.com')
        }
    }, [panel])

    return <Signup />
}

export const Default: StoryFn<StoryArgs> = Template.bind({})

export const SelfHosted: StoryFn<StoryArgs> = Template.bind({})
SelfHosted.args = { cloud: false, googleOAuth: false, github: false, gitlab: false }

export const PasswordStep: StoryFn<StoryArgs> = Template.bind({})
PasswordStep.args = { panel: '2: Password' }

export const ProfileStep: StoryFn<StoryArgs> = Template.bind({})
ProfileStep.args = { panel: '3: Profile' }

export const PendingOAuthConnection: StoryFn<StoryArgs> = Template.bind({})
PendingOAuthConnection.args = { pendingOAuthConnection: true }
