// Signup.stories.tsx
import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { MockSignature } from '~/mocks/utils'

const meta: Meta = {
    title: 'Scenes-Other/Org Member Invites',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me': () => [
                    200,
                    {
                        ...MOCK_DEFAULT_USER,
                        organization: {
                            membership_level: OrganizationMembershipLevel.Owner,
                        },
                    },
                ],
                '/api/organizations/@current/': (): MockSignature => [
                    200,
                    { ...MOCK_DEFAULT_ORGANIZATION, membership_level: OrganizationMembershipLevel.Owner },
                ],
            },
        }),
    ],
}
export default meta
export const CurrentUserIsOwner = (): JSX.Element => {
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
        router.actions.push(urls.settings('organization-members'))
    }, [])
    return <App />
}

export const CurrentUserIsAdmin = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: false,
                realm: 'hosted-clickhouse',
                available_social_auth_providers: { github: false, gitlab: false, 'google-oauth2': false, saml: false },
            },
            '/api/organizations/@current/': (): MockSignature => [
                200,
                { ...MOCK_DEFAULT_ORGANIZATION, membership_level: OrganizationMembershipLevel.Admin },
            ],
        },
    })
    useEffect(() => {
        router.actions.push(urls.settings('organization-members'))
    }, [])
    return <App />
}

export const CurrentUserIsMember = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud: false,
                realm: 'hosted-clickhouse',
                available_social_auth_providers: { github: false, gitlab: false, 'google-oauth2': false, saml: false },
            },
            '/api/organizations/@current/': (): MockSignature => [
                200,
                { ...MOCK_DEFAULT_ORGANIZATION, membership_level: OrganizationMembershipLevel.Member },
            ],
        },
    })
    useEffect(() => {
        router.actions.push(urls.settings('organization-members'))
    }, [])
    return <App />
}
