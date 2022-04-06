// PasswordReset.stories.tsx
import { Meta } from '@storybook/react'
import { PasswordReset } from './PasswordReset'
import React, { useEffect } from 'react'
import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { passwordResetLogic } from 'scenes/authentication/passwordResetLogic'

// some metadata and optional parameters
export default {
    title: 'Scenes-Other/Password Reset',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
} as Meta

// export more stories with different state
export const NoSMTP = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: false,
                realm: 'hosted-clickhouse',
                available_social_auth_providers: { github: false, gitlab: false, 'google-oauth2': false, saml: false },
                email_service_available: false,
            },
        },
    })
    return <PasswordReset />
}
export const Initial = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: false,
                realm: 'hosted-clickhouse',
                available_social_auth_providers: { github: false, gitlab: false, 'google-oauth2': false, saml: false },
                email_service_available: true,
            },
        },
        post: {
            '/api/reset': {},
        },
    })
    return <PasswordReset />
}
export const Success = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: false,
                realm: 'hosted-clickhouse',
                available_social_auth_providers: { github: false, gitlab: false, 'google-oauth2': false, saml: false },
                email_service_available: true,
            },
        },
        post: {
            '/api/reset': {},
        },
    })
    useEffect(() => {
        passwordResetLogic.actions.reset({ email: 'test@posthog.com' })
    }, [])
    return <PasswordReset />
}
