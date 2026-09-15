import {
    PENDING_OAUTH_CONNECTION_FIXTURE,
    setPendingOAuthConnectionCookie,
} from 'scenes/authentication/shared/pendingOAuthConnection.mock'

import type { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { Login } from './Login'
import { loginLogic } from './loginLogic'

type StoryArgs = {
    cloud: boolean
    region: 'US' | 'EU'
    googleOAuth: boolean
    github: boolean
    gitlab: boolean
    samlAvailable: boolean
    ssoEnforcement: 'none' | 'google-oauth2' | 'github' | 'gitlab' | 'saml'
    generalError: 'none' | 'invalid_credentials' | 'code_based_verification_sent'
    pendingOAuthConnection: boolean
    noLoginMethod: boolean
    next: string
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Login',
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    argTypes: {
        cloud: { control: 'boolean', name: 'Cloud' },
        region: { control: 'select', options: ['US', 'EU'], name: 'Region', if: { arg: 'cloud' } },
        googleOAuth: { control: 'boolean', name: 'Google OAuth' },
        github: { control: 'boolean', name: 'GitHub' },
        gitlab: { control: 'boolean', name: 'GitLab' },
        samlAvailable: { control: 'boolean', name: 'SAML available' },
        ssoEnforcement: {
            control: 'select',
            name: 'SSO enforcement',
            options: ['none', 'google-oauth2', 'github', 'gitlab', 'saml'],
        },
        generalError: {
            control: 'select',
            name: 'General error',
            options: ['none', 'invalid_credentials', 'code_based_verification_sent'],
        },
        pendingOAuthConnection: { control: 'boolean', name: 'Pending OAuth connection' },
        noLoginMethod: { control: 'boolean', name: 'No sign-in method set up' },
        next: { control: 'text', name: 'Pending deep link (?next=)' },
    },
    args: {
        cloud: true,
        region: 'US',
        googleOAuth: true,
        github: true,
        gitlab: true,
        samlAvailable: false,
        ssoEnforcement: 'none',
        generalError: 'none',
        pendingOAuthConnection: false,
        noLoginMethod: false,
        next: '',
    },
}
export default meta

const Template: StoryFn<StoryArgs> = ({
    cloud,
    region,
    googleOAuth,
    github,
    gitlab,
    samlAvailable,
    ssoEnforcement,
    generalError,
    pendingOAuthConnection,
    noLoginMethod,
    next,
}) => {
    const enforcement = ssoEnforcement === 'none' ? null : ssoEnforcement
    // Set synchronously: the scene reads the cookie while it mounts during this same render.
    setPendingOAuthConnectionCookie(pendingOAuthConnection ? PENDING_OAUTH_CONNECTION_FIXTURE : null)

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
                    saml: samlAvailable,
                },
            },
        },
        post: {
            '/api/login/precheck': {
                sso_enforcement: enforcement,
                saml_available: samlAvailable,
                ...(noLoginMethod ? { password_login_available: false, social_providers: [] } : {}),
            },
        },
    })

    useEffect(() => {
        router.actions.replace('/login', next ? { next } : {})
    }, [next])

    useEffect(() => {
        if (enforcement || noLoginMethod) {
            loginLogic.actions.setLoginValue('email', 'test@posthog.com')
            loginLogic.actions.precheck({ email: 'test@posthog.com' })
        }
    }, [enforcement, noLoginMethod])

    useEffect(() => {
        if (generalError !== 'none') {
            const messages: Record<string, string> = {
                invalid_credentials: 'Invalid email or password.',
                code_based_verification_sent: 'Check your email to verify your account.',
            }
            loginLogic.actions.setGeneralError(generalError, messages[generalError] ?? '')
        } else {
            loginLogic.actions.clearGeneralError()
        }
    }, [generalError])

    return <Login />
}

export const Default: StoryFn<StoryArgs> = Template.bind({})

export const SelfHosted: StoryFn<StoryArgs> = Template.bind({})
SelfHosted.args = { cloud: false, googleOAuth: false, github: false, gitlab: false, samlAvailable: false }

export const CloudEU: StoryFn<StoryArgs> = Template.bind({})
CloudEU.args = { region: 'EU' }

export const SSOEnforced: StoryFn<StoryArgs> = Template.bind({})
SSOEnforced.args = { ssoEnforcement: 'google-oauth2' }

export const SAMLAvailable: StoryFn<StoryArgs> = Template.bind({})
SAMLAvailable.args = { samlAvailable: true }

export const LoginError: StoryFn<StoryArgs> = Template.bind({})
LoginError.args = { generalError: 'invalid_credentials' }

export const PendingOAuthConnection: StoryFn<StoryArgs> = Template.bind({})
PendingOAuthConnection.storyName = 'Pending OAuth connection'
PendingOAuthConnection.args = { pendingOAuthConnection: true }

export const EmailVerification: StoryFn<StoryArgs> = Template.bind({})
EmailVerification.args = { generalError: 'code_based_verification_sent' }

// A dead end needs every provider off: one linked provider is a way in, so the banner would not show.
const NO_SOCIAL = { googleOAuth: false, github: false, gitlab: false }

export const NoLoginMethod: StoryFn<StoryArgs> = Template.bind({})
NoLoginMethod.storyName = 'No sign-in method set up'
NoLoginMethod.args = { noLoginMethod: true, ...NO_SOCIAL }

export const NoLoginMethodWithPendingOAuthConnection: StoryFn<StoryArgs> = Template.bind({})
NoLoginMethodWithPendingOAuthConnection.storyName = 'No sign-in method set up, pending OAuth connection'
NoLoginMethodWithPendingOAuthConnection.args = {
    noLoginMethod: true,
    pendingOAuthConnection: true,
    next: '/oauth/authorize?client_id=abc&scope=read',
    ...NO_SOCIAL,
}
