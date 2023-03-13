// Login.stories.tsx
import { Meta } from '@storybook/react'
import { Login } from './Login'
import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { useEffect } from 'react'
import preflightJson from '../../mocks/fixtures/_preflight.json'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { loginLogic } from './loginLogic'

export default {
    title: 'Scenes-Other/Login',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/login/precheck': { sso_enforcement: null, saml_available: false },
            },
        }),
    ],
} as Meta

export const Cloud = (): JSX.Element => {
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
export const CloudEU = (): JSX.Element => {
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
export const CloudWithGoogleLoginEnforcement = (): JSX.Element => {
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
export const SelfHosted = (): JSX.Element => {
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

export const SelfHostedWithSAML = (): JSX.Element => {
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

export const SSOError = (): JSX.Element => {
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
