import type { Meta, StoryFn } from '@storybook/react'
import { HttpResponse, delay } from 'msw'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { InviteSignup } from './InviteSignup'
import { inviteSignupLogic } from './inviteSignupLogic'

const MOCK_INVITE_ID = '1234'

type StoryArgs = {
    scenario: 'new-user' | 'existing-account' | 'invalid-link'
    cloud: boolean
    googleOAuth: boolean
    github: boolean
    gitlab: boolean
    ssoEnforcement: 'none' | 'google-oauth2' | 'github' | 'gitlab' | 'saml'
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Invite Signup (paper-desk)',
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: { [FEATURE_FLAGS.AUTH_FLOW_VARIANT]: 'paper-desk' },
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/signup/${MOCK_INVITE_ID}/`]: () => [
                    200,
                    {
                        id: MOCK_INVITE_ID,
                        target_email: 'jane@acme.com',
                        first_name: 'Jane Doe',
                        organization_name: 'Acme Corp',
                    },
                ],
                '/api/signup/not-found/': () => [404, { detail: 'Invite not found or already used.' }],
            },
            post: {
                '/api/signup': async () => {
                    await delay(1000)
                    return HttpResponse.json({ success: true })
                },
                [`/api/signup/${MOCK_INVITE_ID}`]: async () => {
                    await delay(1000)
                    return HttpResponse.json({ success: true })
                },
            },
        }),
    ],
    argTypes: {
        scenario: {
            control: 'select',
            name: 'Scenario',
            options: ['new-user', 'existing-account', 'invalid-link'],
        },
        cloud: { control: 'boolean', name: 'Cloud' },
        googleOAuth: { control: 'boolean', name: 'Google OAuth' },
        github: { control: 'boolean', name: 'GitHub' },
        gitlab: { control: 'boolean', name: 'GitLab' },
        ssoEnforcement: {
            control: 'select',
            name: 'SSO enforcement',
            options: ['none', 'google-oauth2', 'github', 'gitlab', 'saml'],
        },
    },
    args: {
        scenario: 'new-user',
        cloud: true,
        googleOAuth: true,
        github: true,
        gitlab: true,
        ssoEnforcement: 'none',
    },
}
export default meta

const Template: StoryFn<StoryArgs> = ({ scenario, cloud, googleOAuth, github, gitlab, ssoEnforcement }) => {
    const enforcement = ssoEnforcement === 'none' ? null : ssoEnforcement
    const isExistingAccount = scenario === 'existing-account'
    const inviteId = scenario === 'invalid-link' ? 'not-found' : MOCK_INVITE_ID

    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud,
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
            '/api/users/@me': isExistingAccount
                ? () => [200, { email: 'jane@acme.com', first_name: 'Jane Doe', organization: { name: 'Acme Corp' } }]
                : () => [500, null],
        },
        post: {
            '/api/login/precheck': { sso_enforcement: enforcement, saml_available: false },
        },
    })

    useDelayedOnMountEffect(() => {
        inviteSignupLogic.actions.prevalidateInvite(inviteId)
    })

    useEffect(() => {
        if (enforcement) {
            inviteSignupLogic.actions.prevalidateInvite(inviteId)
        }
    }, [enforcement, inviteId])

    return <InviteSignup />
}

export const Default: StoryFn<StoryArgs> = Template.bind({})

export const NewUserCloud: StoryFn<StoryArgs> = Template.bind({})
NewUserCloud.args = { scenario: 'new-user', cloud: true }

export const NewUserSelfHosted: StoryFn<StoryArgs> = Template.bind({})
NewUserSelfHosted.args = {
    scenario: 'new-user',
    cloud: false,
    googleOAuth: false,
    github: false,
    gitlab: false,
}

export const ExistingAccount: StoryFn<StoryArgs> = Template.bind({})
ExistingAccount.args = { scenario: 'existing-account' }

export const InvalidLink: StoryFn<StoryArgs> = Template.bind({})
InvalidLink.args = { scenario: 'invalid-link' }

export const SSOEnforced: StoryFn<StoryArgs> = Template.bind({})
SSOEnforced.args = { ssoEnforcement: 'google-oauth2' }
