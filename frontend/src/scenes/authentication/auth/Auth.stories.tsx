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
import { userLogic } from 'scenes/userLogic'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { arrivedFromWebsiteLogic } from '../shared/arrivedFromWebsiteLogic'
import { Auth } from './Auth'
import { authLogic } from './authLogic'
import { loginLogic } from './loginLogic'
import { signupLogic } from './signupLogic'

const STEP_OPTIONS = [
    'Email',
    'Login',
    'Login code',
    'New person on an SSO domain',
    'Signup credentials',
    'Signup profile',
    'Pending invite',
] as const
type StepOption = (typeof STEP_OPTIONS)[number]
const NEW_ACCOUNT_STEPS: StepOption[] = [
    'New person on an SSO domain',
    'Signup credentials',
    'Signup profile',
    'Pending invite',
]

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
    signedOutForSessionRisk: boolean
    noSignInMethod: boolean
    precheckFails: boolean
    emailTaken: boolean
    canCreateOrg: boolean
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
            options: [...STEP_OPTIONS],
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
        signedOutForSessionRisk: { control: 'boolean', name: 'Signed out for session risk' },
        noSignInMethod: { control: 'boolean', name: 'Account has no sign-in method' },
        precheckFails: { control: 'boolean', name: 'Login precheck fails' },
        emailTaken: { control: 'boolean', name: 'Signup finds the email taken' },
        canCreateOrg: { control: 'boolean', name: 'Signups allowed' },
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
        signedOutForSessionRisk: false,
        noSignInMethod: false,
        precheckFails: false,
        emailTaken: false,
        canCreateOrg: true,
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
    signedOutForSessionRisk,
    noSignInMethod,
    precheckFails,
    emailTaken,
    canCreateOrg,
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
                can_create_org: canCreateOrg,
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
            '/api/login/precheck': () =>
                precheckFails
                    ? [429, { type: 'throttled_error', code: 'throttled', detail: 'Request was throttled.' }]
                    : [
                          200,
                          {
                              account_exists: !NEW_ACCOUNT_STEPS.includes(step),
                              sso_enforcement: enforcement,
                              saml_available: samlAvailable || step === 'New person on an SSO domain',
                              password_login_available: !noSignInMethod,
                          },
                      ],
            '/api/signup/precheck': () =>
                emailTaken
                    ? [
                          409,
                          {
                              email_exists: true,
                              code: 'account_exists',
                              detail: 'There is already an account with this email address.',
                          },
                      ]
                    : [
                          200,
                          {
                              email_exists: false,
                              pending_invite: step === 'Pending invite' ? { organization_name: 'Hogflix' } : null,
                          },
                      ],
        },
    })

    useDelayedOnMountEffect(() => userLogic.actions.loadUserSuccess(null))

    useEffect(() => {
        router.actions.push(
            entry === 'signup' ? '/signup' : '/login',
            signedOutForSessionRisk ? { reason: 'session_risk' } : {}
        )
    }, [entry, signedOutForSessionRisk])

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
    }, [step, enforcement, precheckFails, emailTaken, canCreateOrg])

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

export const NewPersonOnSSODomain: StoryFn<StoryArgs> = Template.bind({})
NewPersonOnSSODomain.storyName = 'New person on an SSO domain'
NewPersonOnSSODomain.args = { step: 'New person on an SSO domain' }

export const SignedOutForSessionRisk: StoryFn<StoryArgs> = Template.bind({})
SignedOutForSessionRisk.storyName = 'Signed out for session risk'
SignedOutForSessionRisk.args = { signedOutForSessionRisk: true }

export const NoSignInMethod: StoryFn<StoryArgs> = Template.bind({})
NoSignInMethod.storyName = 'Account with no sign-in method'
NoSignInMethod.args = { step: 'Login', noSignInMethod: true, googleOAuth: false, github: false, gitlab: false }

export const PrecheckFailed: StoryFn<StoryArgs> = Template.bind({})
PrecheckFailed.storyName = 'Login step when the precheck fails'
PrecheckFailed.args = { step: 'Login', precheckFails: true }

export const EmailTakenOnSignup: StoryFn<StoryArgs> = Template.bind({})
EmailTakenOnSignup.storyName = 'Signup finds the email taken'
EmailTakenOnSignup.args = { step: 'Signup credentials', emailTaken: true }

export const NewPersonWithSignupsOff: StoryFn<StoryArgs> = Template.bind({})
NewPersonWithSignupsOff.storyName = 'New person where signups are off'
NewPersonWithSignupsOff.args = { step: 'Signup credentials', canCreateOrg: false, cloud: false }
