// Signup.stories.tsx
import { Meta } from '@storybook/react'
import React, { useEffect } from 'react'
import { Signup } from './Signup'
import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { userLogic } from 'scenes/userLogic'
import preflightJson from '~/mocks/fixtures/_preflight.json'

export default {
    title: 'Scenes-Other/Signup',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
    decorators: [
        mswDecorator({
            get: { '/api/users/@me': () => [500, null] },
            post: { '/api/signup': (_, __, ctx) => [ctx.delay(1000), ctx.status(200), ctx.json({ success: true })] },
        }),
    ],
} as Meta

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
    useEffect(() => {
        userLogic.actions.loadUserSuccess(null)
    }, [])
    return <Signup />
}

export const SelfHostedSSO = (): JSX.Element => {
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
    useEffect(() => {
        userLogic.actions.loadUserSuccess(null)
    }, [])
    return <Signup />
}

export const Cloud = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: true,
                realm: 'cloud',
                available_social_auth_providers: { github: false, gitlab: false, 'google-oauth2': false, saml: false },
            },
        },
    })
    useEffect(() => {
        userLogic.actions.loadUserSuccess(null)
    }, [])
    return <Signup />
}
