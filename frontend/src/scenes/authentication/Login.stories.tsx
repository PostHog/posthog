// Login.stories.tsx
import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

import preflightJson from '../../mocks/fixtures/_preflight.json'
import { Login } from './Login'
import { Login2FA } from './Login2FA'
import { loginLogic } from './loginLogic'

const meta: Meta = {
    title: 'Scenes-Other/Login',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: {
            waitForSelector: '.BridgePage__left__message--enter-done',
        },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/login/precheck': { sso_enforcement: null, saml_available: false },
            },
        }),
    ],
}
export default meta

export const Cloud: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: true,
                realm: 'cloud',
                can_create_org: true,
                available_social_auth_providers: { github: true, gitlab: true, 'google-oauth2': true, saml: false },
            },
        },
    })
    return <Login />
}

export const CloudEU: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: true,
                region: 'EU',
                realm: 'cloud',
                can_create_org: true,
                available_social_auth_providers: { github: true, gitlab: true, 'google-oauth2': true, saml: false },
            },
        },
    })
    return <Login />
}

export const CloudWithGoogleLoginEnforcement: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: true,
                realm: 'cloud',
                can_create_org: true,
                available_social_auth_providers: { github: true, gitlab: true, 'google-oauth2': true, saml: false },
            },
        },
        post: {
            '/api/login/precheck': { sso_enforcement: 'google-oauth2', saml_available: false },
        },
    })
    useEffect(() => {
        // Trigger pre-check
        loginLogic.actions.setLoginValue('email', 'test@posthog.com')
        loginLogic.actions.precheck({ email: 'test@posthog.com' })
    }, [])
    return <Login />
}
CloudWithGoogleLoginEnforcement.parameters = {
    testOptions: {
        waitForSelector: '[href^="/login/google-oauth2/"]',
    },
}

export const SelfHosted: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: false,
                realm: 'hosted-clickhouse',
                available_social_auth_providers: { github: false, gitlab: false, 'google-oauth2': false, saml: false },
            },
        },
    })
    return <Login />
}

export const SelfHostedWithSAML: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: false,
                realm: 'hosted-clickhouse',
                available_social_auth_providers: { github: false, gitlab: false, 'google-oauth2': false, saml: true },
            },
        },
    })
    return <Login />
}
SelfHostedWithSAML.parameters = {
    testOptions: {
        waitForSelector: '[href^="/login/saml/"]',
    },
}

export const SSOError: StoryFn = () => {
    useStorybookMocks({
        get: {
            '/_preflight': preflightJson,
        },
    })

    useEffect(() => {
        // Change the URL
        router.actions.push(`${urls.login()}?error_code=improperly_configured_sso`)
    }, [])

    return <Login />
}

export const SecondFactor: StoryFn = () => {
    useEffect(() => {
        // Change the URL
        router.actions.push(urls.login2FA())
    }, [])
    return <Login2FA />
}
