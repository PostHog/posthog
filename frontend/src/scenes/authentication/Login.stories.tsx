// Login.stories.tsx
import { Meta } from '@storybook/react'
import { Login } from './Login'
import { useStorybookMocks } from '~/mocks/browser'
import React, { useEffect } from 'react'
import preflightJson from '../../mocks/fixtures/_preflight.json'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export default {
    title: 'Scenes-Other/Login',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as Meta

// export more stories with different state
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
        // change the URL
        router.actions.push(`${urls.login()}?error_code=improperly_configured_sso`)
    }, [])
    return <Login />
}
