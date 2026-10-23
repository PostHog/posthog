import { WEBSITE_REFERRER, setDocumentReferrer } from 'scenes/authentication/shared/authReferrer.mock'
import { setLastLoginMethodCookie } from 'scenes/authentication/shared/lastLoginMethod.mock'
import {
    PENDING_OAUTH_CONNECTION_FIXTURE,
    setPendingOAuthConnectionCookie,
} from 'scenes/authentication/shared/pendingOAuthConnection.mock'

import type { Meta, StoryFn } from '@storybook/react'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { loginLogic } from 'scenes/authentication/login/loginLogic'
import { signupLogic } from 'scenes/authentication/signup/signupForm/signupLogic'
import { userLogic } from 'scenes/userLogic'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { arrivedFromWebsiteLogic } from '../shared/arrivedFromWebsiteLogic'
import { Auth } from './Auth'
import { authLogic } from './authLogic'

type StepOption = 'Email' | 'Login' | 'Login code' | 'Signup credentials' | 'Signup profile' | 'Pending invite'

type StoryArgs = {
    entry: 'login' | 'signup'
    step: StepOption
    cloud: boolean
    region: 'US' | 'EU'
    googleOAuth: boolean
    github: boolean
    gitlab: boolean
    samlAvailable: boolean
    ssoEnforcement: 'none' | 'google-oauth2' | 'github' | 'gitlab' | 'saml'
    generalError: 'none' | 'invalid_credentials' | 'no_new_organizations'
    pendingOAuthConnection: boolean
    arrivedFromWebsite: boolean
    hasLoggedInBefore: boolean
}

const EMAIL = 'test@posthog.com'

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Auth',
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    argTypes: {
        entry: { control: 'select', options: ['login', 'signup'], name: 'Entry URL' },
        step: {
            control: 'select',
            name: 'Step',
            options: [
                'Email',
                'Login',
                'Login code',
                'Signup credentials',
                'Signup profile',
                'Pending invite',
            ] satisfies StepOption[],
        },
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
            options: ['none', 'invalid_credentials', 'no_new_organizations'],
        },
        pendingOAuthConnection: { control: 'boolean', name: 'Pending OAuth connection' },
        arrivedFromWebsite: { control: 'boolean', name: 'Arrived from posthog.com' },
        hasLoggedInBefore: { control: 'boolean', name: 'Has logged in before' },
    },
    args: {
        entry: 'login',
        step: 'Email',
        cloud: true,
        region: 'US',
        googleOAuth: true,
        github: true,
        gitlab: true,
        samlAvailable: false,
        ssoEnforcement: 'none',
        generalError: 'none',
        pendingOAuthConnection: false,
        arrivedFromWebsite: false,
        hasLoggedInBefore: true,
    },
}
export default meta

const ERROR_DETAILS: Record<string, string> = {
    invalid_credentials: 'Invalid email or password.',
}

const Template: StoryFn<StoryArgs> = ({
    entry,
    step,
    cloud,
    region,
    googleOAuth,
    github,
    gitlab,
    samlAvailable,
    ssoEnforcement,
    generalError,
    pendingOAuthConnection,
    arrivedFromWebsite,
    hasLoggedInBefore,
}) => {
    const enforcement = ssoEnforcement === 'none' ? null : ssoEnforcement
    // Set synchronously: the scene reads the cookies while it mounts during this same render.
    setPendingOAuthConnectionCookie(pendingOAuthConnection ? PENDING_OAUTH_CONNECTION_FIXTURE : null)
    setDocumentReferrer(arrivedFromWebsite ? WEBSITE_REFERRER : '')
    setLastLoginMethodCookie(hasLoggedInBefore ? 'password' : null)

    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud,
                region: cloud ? region : undefined,
                realm: cloud ? 'cloud' : 'hosted-clickhouse',
                is_debug: cloud,
                can_create_org: true,
                available_social_auth_providers: {
                    'google-oauth2': googleOAuth,
                    github,
                    gitlab,
                    saml: samlAvailable,
                },
            },
            '/api/users/@me': () => [500, null],
        },
        post: {
            '/api/login/precheck': {
                account_exists: step !== 'Signup credentials' && step !== 'Signup profile' && step !== 'Pending invite',
                sso_enforcement: enforcement,
                saml_available: samlAvailable,
            },
            '/api/signup/precheck': {
                email_exists: false,
                pending_invite: step === 'Pending invite' ? { organization_name: 'Hogflix' } : null,
            },
        },
    })

    useDelayedOnMountEffect(() => userLogic.actions.loadUserSuccess(null))

    useEffect(() => {
        router.actions.push(entry === 'signup' ? '/signup' : '/login')
    }, [entry])

    useEffect(() => {
        arrivedFromWebsiteLogic.findMounted()?.actions.setArrivedFromWebsite(arrivedFromWebsite)
    }, [arrivedFromWebsite])

    useEffect(() => {
        authLogic.actions.backToEmail()
        if (step === 'Email') {
            return
        }
        loginLogic.actions.setLoginValue('email', EMAIL)
        authLogic.actions.continueWithEmail()
    }, [step, enforcement])

    useEffect(() => {
        if (step === 'Login code') {
            loginLogic.actions.setCodeVerificationRequired(EMAIL)
        }
    }, [step])

    // The signup precheck answers asynchronously and opens panel 1, so move on only once it has
    const { panel } = useValues(signupLogic)
    useEffect(() => {
        if (step === 'Signup profile' && panel === 1) {
            signupLogic.actions.setPanel(2)
        }
    }, [step, panel])

    useEffect(() => {
        if (generalError !== 'none') {
            loginLogic.actions.setGeneralError(generalError, ERROR_DETAILS[generalError] ?? '')
        } else {
            loginLogic.actions.clearGeneralError()
        }
    }, [generalError])

    return <Auth key={String(hasLoggedInBefore)} />
}

export const Default: StoryFn<StoryArgs> = Template.bind({})

export const FirstLoginOnThisBrowser: StoryFn<StoryArgs> = Template.bind({})
FirstLoginOnThisBrowser.storyName = 'First login on this browser'
FirstLoginOnThisBrowser.args = { hasLoggedInBefore: false }

export const SignupEntry: StoryFn<StoryArgs> = Template.bind({})
SignupEntry.storyName = 'Signup entry'
SignupEntry.args = { entry: 'signup' }

export const SelfHosted: StoryFn<StoryArgs> = Template.bind({})
SelfHosted.args = { cloud: false, googleOAuth: false, github: false, gitlab: false, samlAvailable: false }

export const SocialSignInError: StoryFn<StoryArgs> = Template.bind({})
SocialSignInError.storyName = 'Social sign-in error'
SocialSignInError.args = { generalError: 'no_new_organizations' }

export const PendingOAuthConnection: StoryFn<StoryArgs> = Template.bind({})
PendingOAuthConnection.storyName = 'Pending OAuth connection'
PendingOAuthConnection.args = { pendingOAuthConnection: true }

export const LoginStep: StoryFn<StoryArgs> = Template.bind({})
LoginStep.args = { step: 'Login' }

export const LoginStepFromSignupEntry: StoryFn<StoryArgs> = Template.bind({})
LoginStepFromSignupEntry.storyName = 'Login step from the signup entry'
LoginStepFromSignupEntry.args = { step: 'Login', entry: 'signup' }

export const LoginError: StoryFn<StoryArgs> = Template.bind({})
LoginError.args = { step: 'Login', generalError: 'invalid_credentials' }

export const SSOEnforced: StoryFn<StoryArgs> = Template.bind({})
SSOEnforced.args = { step: 'Login', ssoEnforcement: 'google-oauth2' }

export const SAMLAvailable: StoryFn<StoryArgs> = Template.bind({})
SAMLAvailable.args = { step: 'Login', samlAvailable: true }

export const LoginCode: StoryFn<StoryArgs> = Template.bind({})
LoginCode.args = { step: 'Login code' }

export const SignupCredentials: StoryFn<StoryArgs> = Template.bind({})
SignupCredentials.args = { step: 'Signup credentials' }

export const SignupCredentialsEU: StoryFn<StoryArgs> = Template.bind({})
SignupCredentialsEU.storyName = 'Signup credentials (EU)'
SignupCredentialsEU.args = { step: 'Signup credentials', region: 'EU' }

export const SignupCredentialsPendingOAuthConnection: StoryFn<StoryArgs> = Template.bind({})
SignupCredentialsPendingOAuthConnection.storyName = 'Signup credentials with a pending OAuth connection'
SignupCredentialsPendingOAuthConnection.args = { step: 'Signup credentials', pendingOAuthConnection: true }

export const SignupProfile: StoryFn<StoryArgs> = Template.bind({})
SignupProfile.args = { step: 'Signup profile' }

export const PendingInvite: StoryFn<StoryArgs> = Template.bind({})
PendingInvite.args = { step: 'Pending invite' }
