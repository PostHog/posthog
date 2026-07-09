import type { Meta, StoryFn } from '@storybook/react'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

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
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Login (paper-desk)',
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: { [FEATURE_FLAGS.AUTH_FLOW_VARIANT]: 'paper-desk' },
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
}) => {
    const enforcement = ssoEnforcement === 'none' ? null : ssoEnforcement

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
            '/api/login/precheck': { sso_enforcement: enforcement, saml_available: samlAvailable },
        },
    })

    useEffect(() => {
        if (enforcement) {
            loginLogic.actions.setLoginValue('email', 'test@posthog.com')
            loginLogic.actions.precheck({ email: 'test@posthog.com' })
        }
    }, [enforcement])

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

export const EmailVerification: StoryFn<StoryArgs> = Template.bind({})
EmailVerification.args = { generalError: 'code_based_verification_sent' }
