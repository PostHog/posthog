// Login.stories.tsx
import { Meta } from '@storybook/react'
import { Login } from './Login'
import { useStorybookMocks } from '~/mocks/browser'
import { useEffect } from 'react'
import preflightJson from '../../mocks/fixtures/_preflight.json'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export default {
    title: 'Scenes-Other/Login',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        chromatic: { disableSnapshot: true },
    },
} as Meta

const sharedMocks = {
    post: {
        '/api/login/precheck': { sso_enforcement: null, saml_available: false },
    },
}

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
        ...sharedMocks,
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
            ...sharedMocks,
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
        ...sharedMocks,
    })
    return <Login />
}

export const SSOError = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/_preflight': preflightJson,
        },
        ...sharedMocks,
    })
    useEffect(() => {
        // change the URL
        router.actions.push(`${urls.login()}?error_code=improperly_configured_sso`)
    }, [])
    return <Login />
}
