// PasswordReset.stories.tsx
import { Meta } from '@storybook/react'
import { useEffect } from 'react'
import { passwordResetLogic } from 'scenes/authentication/passwordResetLogic'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { PasswordReset } from './PasswordReset'

// some metadata and optional parameters
const meta: Meta = {
    title: 'Scenes-Other/Password Reset',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta
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
        passwordResetLogic.actions.setRequestPasswordResetValues({ email: 'test@posthog.com' })
        passwordResetLogic.actions.submitRequestPasswordResetSuccess({ email: 'test@posthog.com' })
    }, [])
    return <PasswordReset />
}
export const Throttled = (): JSX.Element => {
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
        passwordResetLogic.actions.setRequestPasswordResetValues({ email: 'test@posthog.com' })
        passwordResetLogic.actions.setRequestPasswordResetManualErrors({ code: 'throttled' })
    }, [])
    return <PasswordReset />
}
