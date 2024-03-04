import { Meta } from '@storybook/react'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

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
                '/api/users/@me': () => [
                    200,
                    {
                        email: 'test@posthog.com',
                        first_name: 'Test PostHog',
                        organization: {
                            name: 'My org',
                            teams: [],
                        },
                        team: {
                            id: 1,
                            name: 'My team',
                        },
                    },
                ],
                'api/organizations/@current/': () => [
                    200,
                    {
                        membership_level: 1,
                        name: 'My org',
                        teams: [],
                    },
                ],
                '/api/organizations/@current/members/': {},
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
    const { loadUser } = useActions(userLogic)
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
    useEffect(() => {
        loadUser()
        router.actions.push(urls.projectHomepage())
    }, [])
    return <App />
}
