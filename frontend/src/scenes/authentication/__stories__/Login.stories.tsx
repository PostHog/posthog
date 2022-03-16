// Login.stories.tsx
import { Meta } from '@storybook/react'
import { Login } from '../Login'
import { useStorybookMocks } from '~/mocks/browser'
import React from 'react'
import preflightJson from '../../../mocks/fixtures/_preflight.json'

export default {
    title: 'Scenes/Authentication/Login',
} as Meta

// export more stories with different state
export const Cloud = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud', can_create_org: true },
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
                available_social_auth_providers: { github: true, gitlab: true, 'google-oauth2': true, saml: true },
            },
        },
    })
    return <Login />
}
