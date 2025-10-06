import { Meta } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { InviteSignup } from './InviteSignup'
import { inviteSignupLogic } from './inviteSignupLogic'

const meta: Meta = {
    title: 'Scenes-Other/InviteSignup',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: {
            waitForSelector: '.BridgePage__left__message--enter-done',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me': () => [500, null],
                '/api/signup/1234/': () => [
                    200,
                    {
                        id: '1234',
                        target_email: 'b*@posthog.com',
                        first_name: 'Jane Doe',
                        organization_name: 'PostHog',
                    },
                ],
            },
            post: {
                '/api/signup': (_, __, ctx) => [ctx.delay(1000), ctx.status(200), ctx.json({ success: true })],
                '/api/signup/1234': (_, __, ctx) => [ctx.delay(1000), ctx.status(200), ctx.json({ success: true })],
                '/api/login/precheck': { sso_enforcement: null, saml_available: false },
            },
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

    useDelayedOnMountEffect(() => {
        inviteSignupLogic.actions.prevalidateInvite('1234')
    })

    return <InviteSignup />
}

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

    useDelayedOnMountEffect(() => {
        inviteSignupLogic.actions.prevalidateInvite('1234')
    })

    return <InviteSignup />
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

    useDelayedOnMountEffect(() => {
        inviteSignupLogic.actions.prevalidateInvite('1234')
    })

    return <InviteSignup />
}

export const InvalidLink = (): JSX.Element => {
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

    useDelayedOnMountEffect(() => {
        inviteSignupLogic.actions.prevalidateInvite('not-found')
    })

    return <InviteSignup />
}

export const LoggedIn = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: true,
                realm: 'cloud',
                can_create_org: true,
                available_social_auth_providers: { github: true, gitlab: true, 'google-oauth2': true, saml: false },
            },
            '/api/users/@me': () => [
                200,
                {
                    email: 'ben@posthog.com',
                    first_name: 'Ben White',
                    organization: {
                        name: 'Other org',
                    },
                },
            ],
        },
    })

    useDelayedOnMountEffect(() => {
        inviteSignupLogic.actions.prevalidateInvite('1234')
    })

    return <InviteSignup />
}

export const LoggedInWrongUser = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: true,
                realm: 'cloud',
                can_create_org: true,
                available_social_auth_providers: { github: true, gitlab: true, 'google-oauth2': true, saml: false },
            },
            '/api/users/@me': () => [
                200,
                {
                    email: 'ben@posthog.com',
                    first_name: 'Ben White',
                    organization: {
                        name: 'Other org',
                    },
                },
            ],
            '/api/signup/1234/': () => [
                400,
                {
                    code: 'invalid_recipient',
                },
            ],
        },
    })

    useDelayedOnMountEffect(() => {
        inviteSignupLogic.actions.prevalidateInvite('1234')
    })

    return (
        <div>
            <div className="border-b border-t p-4 font-bold">HEADER AREA</div>
            <InviteSignup />
        </div>
    )
}

export const SSOEnforcedSaml = (): JSX.Element => {
    useStorybookMocks({
        post: {
            '/api/login/precheck': { sso_enforcement: 'saml', saml_available: true },
        },
    })

    useDelayedOnMountEffect(() => {
        inviteSignupLogic.actions.prevalidateInvite('1234')
    })

    return (
        <div>
            <div className="border-b border-t p-4 font-bold">HEADER AREA</div>
            <InviteSignup />
        </div>
    )
}

export const SSOEnforcedGoogle = (): JSX.Element => {
    useStorybookMocks({
        post: { '/api/login/precheck': { sso_enforcement: 'google-oauth2', saml_available: false } },
    })

    useDelayedOnMountEffect(() => {
        inviteSignupLogic.actions.prevalidateInvite('1234')
    })

    return (
        <div>
            <div className="border-b border-t p-4 font-bold">HEADER AREA</div>
            <InviteSignup />
        </div>
    )
}
