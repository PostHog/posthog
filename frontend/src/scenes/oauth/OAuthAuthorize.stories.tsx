import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    title: 'Scenes-App/OAuth/Authorize',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        testOptions: {
            waitForSelector: '.max-w-2xl',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/oauth_application/metadata/test-client-id/': {
                    id: '123',
                    client_id: 'test-client-id',
                    name: 'Test OAuth Application',
                    description: 'This is a test OAuth application for development',
                    created_at: '2023-01-01T00:00:00Z',
                    updated_at: '2023-01-01T00:00:00Z',
                },
                '/api/projects/': {
                    results: [
                        {
                            id: 1,
                            name: 'Default Project',
                            organization: {
                                id: '1',
                                name: 'Default Organization',
                                slug: 'default-org',
                            },
                        },
                        {
                            id: 2,
                            name: 'Analytics Project',
                            organization: {
                                id: '1',
                                name: 'Default Organization',
                                slug: 'default-org',
                            },
                        },
                    ],
                },
            },
            post: {
                '/oauth/authorize/': {
                    redirect_to: 'https://example.com/callback?code=test-auth-code&state=test-state',
                },
            },
        }),
    ],
}

export default meta

export const DefaultScopes: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        const params = new URLSearchParams({
            client_id: 'test-client-id',
            redirect_uri: 'https://example.com/callback',
            response_type: 'code',
            state: 'test-state',
        })
        router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
    })

    return <App />
}

export const WithScopes: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        const params = new URLSearchParams({
            client_id: 'test-client-id',
            redirect_uri: 'https://app.example.com/oauth/callback',
            response_type: 'code',
            state: 'test-state',
            scope: 'experiment:read experiment:write query:read feature_flag:write',
        })
        router.actions.push(`${urls.oauthAuthorize()}?${params.toString()}`)
    })

    return <App />
}
