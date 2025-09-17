import { Meta } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { SignupContainer } from './SignupContainer'

const meta: Meta = {
    title: 'Scenes-Other/Signup',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: { '/api/users/@me': () => [500, null] },
            post: { '/api/signup': (_, __, ctx) => [ctx.delay(1000), ctx.status(200), ctx.json({ success: true })] },
        }),
    ],
}
export default meta

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

    useDelayedOnMountEffect(() => userLogic.actions.loadUserSuccess(null))

    return <SignupContainer />
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

    useDelayedOnMountEffect(() => userLogic.actions.loadUserSuccess(null))

    return <SignupContainer />
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

    useDelayedOnMountEffect(() => userLogic.actions.loadUserSuccess(null))

    return <SignupContainer />
}
