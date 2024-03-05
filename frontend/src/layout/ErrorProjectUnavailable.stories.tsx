import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

import preflightJson from '../mocks/fixtures/_preflight.json'

const meta: Meta = {
    title: 'Scenes-App/Error Project Unavailable',
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    region: 'EU',
                    realm: 'cloud',
                    can_create_org: true,
                    available_social_auth_providers: { github: true, gitlab: true, 'google-oauth2': true, saml: false },
                },
                '/api/projects/@current/': () => [
                    403,
                    {
                        code: 'project_unavailable',
                        type: 'authentication_error',
                        detail: 'You do not have access to this project',
                    },
                ],
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
        mockDate: '2023-02-01',
    },
}
export default meta

export const ErrorProjectUnavailableAccessRevoked = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/users/@me/': () => [
                200,
                {
                    email: 'test@posthog.com',
                    first_name: 'Test PostHog',
                    organization: {
                        name: 'Test org',
                        teams: [],
                    },
                    team: {
                        id: 1,
                        name: 'Test team',
                    },
                },
            ],
            'api/organizations/@current/': () => [
                200,
                {
                    membership_level: 15,
                    name: 'Test org',
                    teams: [],
                },
            ],
        },
    })
    useEffect(() => {
        router.actions.push(urls.projectHomepage())
    }, [])
    return <App />
}
export const ErrorProjectUnavailableNoProjects = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/users/@me/': () => [
                200,
                {
                    email: 'test@posthog.com',
                    first_name: 'Test PostHog',
                    organization: {
                        name: 'Test org',
                        teams: [],
                    },
                    team: null,
                },
            ],
            'api/organizations/@current/': () => [
                200,
                {
                    membership_level: 1,
                    name: 'Test org',
                    teams: [],
                },
            ],
        },
    })
    useEffect(() => {
        router.actions.push(urls.projectHomepage())
    }, [])
    return <App />
}
